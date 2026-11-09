# 第一批：公网访问 + 真实登录 —— 设计稿（待确认，未实现）

> 2026-11-09维护说明：账号/会话/admin-member/本机ticket已在0022落地，发布仓已成为主线。下文是历史方案；Cookie/CSRF实现与部分建议不同，按当前architecture §9执行。网络证书与法规文字仅是当时调研记录，本轮未复核，不应当作当前部署或合规结论。服务器清空、重置密码等操作不由本文自动授权。

- 编号：t98u ｜ 日期：2026-11-03 ｜ 状态：**草案，待用户确认后再动代码**
- 依据：发布仓 `D:\CodeWork\TestAgent\release\testagent`（HEAD 8d9f36e）的实际代码；路线图 `D:\CodeWork\TestAgent\specs\test-agent-platform\design\team-readiness-roadmap-t33u.md`
- 已确认的前提：**没有域名**；服务器数据可以清空，不做旧数据迁移（数据库迁移仍按正常编号走）；安全组只开 443。

---

## 0. 结论速览

| 项 | 决定 |
|---|---|
| 代码落在哪个仓 | **发布仓 `D:\CodeWork\TestAgent\release\testagent` 作为今后主线**（见 §7） |
| 账号 | 新表 `users`，角色只有 `admin` / `member`，密码 argon2id |
| 会话 | **服务端会话 + HttpOnly Cookie**（不用 JWT），会话存 PostgreSQL |
| CSRF | SameSite=Lax + 现有 Origin 校验 + 会话绑定的 `X-CSRF-Token` 头（双重提交） |
| 防爆破 | 每 IP 限速 + 每账号连续失败 5 次锁 15 分钟 |
| 首个管理员 | `.env` 里的 `TESTAGENT_ADMIN_USER` / `TESTAGENT_ADMIN_PASSWORD`（仅在用户表为空时生效）+ 命令行 `testagent user ...` 兜底 |
| 旧共享 token | **移除**浏览器用的 `#t=` 共享 token；`TESTAGENT_ACCESS_TOKEN` 设了也忽略并告警。个人 API Token 推迟到后续批次 |
| `local-user` | 用请求级上下文变量替换 27 处默认值，记录真实用户名；后台任务仍记 `system` / `scheduler` |
| 公网暴露 | compose 新增 Caddy 服务，只监听 443；主方案 **公网 IP + Caddy 内部证书（自签）**；可选升级为 Let's Encrypt IP 证书；有备案域名后再走域名证书 |
| 演示被测系统 | 不经代理，不开安全组，只在 compose 内网 `http://demo:8766`（宿主机仍只绑 127.0.0.1） |
| 迁移编号 | `0022_users_sessions.sql` |
| 工作量 | 约 **3.5–4 人日** |

---

## 1. 现状（读代码得到）

- `src/testagent/core/auth.py` 的 `LocalAuthMiddleware`：
  1. Host 必须是回环地址或 `TESTAGENT_ALLOWED_HOSTS` 里的名字；
  2. 有 `Origin` 头时必须和 `request.base_url` 一致；
  3. `/api/` 下（除 `/api/v1/health`）必须带 `Authorization: Bearer <共享token>`，用 `compare_digest` 比较。
- `src/testagent/launch.py`：token 取 `TESTAGENT_ACCESS_TOKEN`（旧名 `TESTAGENT_DEV_TOKEN`），否则每次启动随机生成；Docker 无头模式把 `Sign in: http://localhost:8765/#t=...` 打到日志。`uvicorn.run(...)` 没开 `proxy_headers`。
- 前端：`web/src/app/token.ts` 把 `#t=` 存进 `sessionStorage`；`web/src/api/client.ts`、`web/src/api/sse.ts`（用 fetch 实现 SSE，因为 EventSource 不能带头）、`ArtifactImage`（截图用 fetch 拿 blob）都手动加 Bearer 头；`AuthGate.tsx` 没 token 时显示“请从启动器重新打开”。
- SSE：唯一的流是 `src/testagent/api/runs.py` 的 `StreamingResponse(text/event-stream)`。
- 操作人：27 处 `actor: str = "local-user"` 默认值（`services/base.py`、各 Service 构造函数、`api/app.py` 的 `runs_factory`、`api/executions.py`、`services/automation.py` 一处写死）。路由层构造 Service 时都没传 actor。后台 Worker/调度/报告已显式传 `system` / `scheduler`。
- 数据库里的操作人字段全是 `text`：审计 `actor`、`confirmed_by`、`decided_by`、`executed_by`、`reviewed_by`、`created_by`（0010/0012），**不需要改列类型**。注意 0001 里有个 `created_by IN ('human','agent')` 是“来源”不是人，不动。
- 迁移：`src/testagent/migrations/NNNN_name.sql`，当前最高 `0021_task_case_binding.sql`。
- 测试：`tests/conftest.py` 用固定 TOKEN 建 app 并给客户端加 Bearer 头；`tests/api/test_auth_api.py` 测中间件。

---

## 2. 用户账号

### 2.1 数据模型（迁移 `0022_users_sessions.sql`）

```sql
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9][a-z0-9._-]{1,31}$'),  -- 存小写，创建后不可改
  display_name text NOT NULL DEFAULT '',
  password_hash text,                         -- argon2id 编码串；NULL = 不能用密码登录（仅本机票据）
  role text NOT NULL DEFAULT 'member' CHECK (role IN ('admin','member')),
  is_active boolean NOT NULL DEFAULT true,
  must_change_password boolean NOT NULL DEFAULT false,
  failed_logins integer NOT NULL DEFAULT 0,
  locked_until timestamptz,
  password_changed_at timestamptz,
  last_login_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash bytea NOT NULL UNIQUE,           -- sha256(会话随机值)，库里不存明文
  csrf_token text NOT NULL,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  ip text, user_agent text
);
CREATE INDEX sessions_user_idx ON sessions(user_id) WHERE revoked_at IS NULL;
```

用户名作为 actor 写进现有 text 字段，所以用户名创建后不可改（改显示名即可）。

### 2.2 密码

- **argon2id**，用 `argon2-cffi`（MIT 许可，新增一个依赖，`docs/third-party-licenses.md` 要补）。参数用库默认（约 64 MiB / t=3），登录时 `check_needs_rehash` 自动升级。
- 规则：长度 10–128，不能等于用户名，不加复杂度规则。
- 用户名不存在时也跑一次假哈希，避免靠响应时间判断用户是否存在；错误信息统一为“用户名或密码错误”。

### 2.3 会话：选 Cookie + 服务端会话，不用 JWT

理由：
1. **能立刻失效**：登出、改密码、禁用账号、管理员重置密码都要马上踢掉旧会话；JWT 要做黑名单，等于又回到服务端存储。
2. **单实例**：平台本来就有实例锁、只允许一个进程连同一个库，会话放 PostgreSQL 没有扩展性问题。
3. **前端更简单更安全**：HttpOnly Cookie 不让 JS 读到凭据（XSS 偷不走），同源 fetch / SSE / 下载 / `<img>` 自动带上，不用再手动拼头。

细节：
- Cookie：`__Host-ta_session`（HttpOnly、Secure、SameSite=Lax、Path=/、无 Domain）。本机 `http://localhost` 开发时浏览器把 localhost 视为安全上下文，Secure 仍可用；`TESTAGENT_COOKIE_SECURE=auto|true|false` 兜底，`auto` = 请求是 https 或回环地址时置 Secure。
- 有效期：闲置 12 小时过期，绝对上限 7 天（`TESTAGENT_SESSION_IDLE_HOURS` / `TESTAGENT_SESSION_MAX_DAYS`）。`last_seen_at` 最多每 5 分钟写一次库。
- 登录成功时轮换会话（防会话固定），并清零失败计数。

### 2.4 CSRF

三层：
1. 会话 Cookie `SameSite=Lax`（跨站 POST 不带 Cookie）；
2. 保留现有 Origin 校验，并加严：非 GET/HEAD/OPTIONS 请求必须有 `Origin`（或 `Referer`）且与平台地址一致；
3. 会话绑定的 CSRF 值：登录时下发非 HttpOnly 的 `ta_csrf` Cookie（SameSite=Strict），前端在写请求里带 `X-CSRF-Token`，服务端和会话行里的 `csrf_token` 比对。

### 2.5 登录限速 / 锁定

- 每 IP：`/auth/login` 每分钟 10 次、每小时 100 次，超了返回 429（内存令牌桶，单实例够用；IP 取 Caddy 传来的 `X-Forwarded-For`，只信任代理）。
- 每账号：连续失败 5 次锁 15 分钟（写库，重启不丢）；锁定期间返回同样的通用错误，界面提示“稍后再试”。管理员可以手动解锁。
- 登录成功和失败都写进访问日志（用户名、IP，绝不记密码）。

### 2.6 接口

| 方法 | 路径 | 谁能用 | 说明 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | 匿名 | `{username,password}` → 设 Cookie，返回 me |
| POST | `/api/v1/auth/logout` | 登录用户 | 吊销当前会话 |
| GET | `/api/v1/auth/me` | 登录用户 | 用户名、显示名、角色、是否需改密 |
| POST | `/api/v1/auth/password` | 登录用户 | 旧密码 + 新密码；吊销本人其它会话 |
| POST | `/api/v1/auth/ticket` | 匿名，仅回环 | 本机启动器的一次性票据换会话（§2.8） |
| GET/POST | `/api/v1/users` | admin | 列表 / 新建（初始密码，默认要求首次登录改密） |
| PATCH | `/api/v1/users/{id}` | admin | 改显示名、角色、启用/禁用、重置密码、解锁；禁用或重置时吊销其全部会话 |

不能删除用户（避免历史 actor 悬空），只能禁用。不能禁用或降级最后一个启用的 admin。

### 2.7 角色权限（最小）

- **admin**：用户管理；**Agent 设置**（模型地址和 API Key）；**被测系统环境的启动命令**（这在服务器上执行命令）。
- **member**：其余全部（需求、模型、用例、任务、执行、缺陷、报告）。

> 安全提示（写进 SECURITY.md）：平台会在容器里执行 AI 生成的 pytest 脚本、访问任意被测地址，**任何登录用户实际上都能在容器里执行代码、让服务器访问内网**。所以账号只发给信任的人；角色划分只是防误操作，不是隔离边界。

### 2.8 首个管理员 & 本机启动器

- **环境变量引导**：启动时若 `users` 表为空且设置了 `TESTAGENT_ADMIN_USER` / `TESTAGENT_ADMIN_PASSWORD`，创建该 admin；表不为空时忽略这两个变量，并在日志提醒“可以从 .env 删掉密码了”。密码只读不打印。
- **命令行兜底**（忘记密码、无环境变量时）：
  `docker compose exec testagent testagent user add <name> --admin`、`... user passwd <name>`、`... user list`、`... user unlock <name>`、`... user disable <name>`。密码交互输入，不走命令行参数（避免进 shell 历史）。
- 用户表为空又没设环境变量：平台照常启动，登录页显示“尚无管理员，请运行 `testagent user add <name> --admin`”。
- **本机 `uv run testagent`（桌面模式）**：保留“一键打开浏览器就登录”的体验——启动器生成 2 分钟有效、只能用一次的票据，打开 `http://localhost:8765/#ticket=...`，前端调 `/auth/ticket` 换成会话 Cookie。只在监听回环地址、非 Docker 无头模式下签发；若无用户则建一个无密码的 `local` 管理员（只能用票据登录）。Docker 部署**不再**打印任何登录链接。

### 2.9 旧 token 怎么处理（建议：移除）

- 删除浏览器的 `#t=` 共享 token 流程（`token.ts`、`AuthGate` 文案、`launch.py` 的 Sign in 打印）。
- `TESTAGENT_ACCESS_TOKEN` / `TESTAGENT_DEV_TOKEN`：设了也忽略，启动时打一行告警。理由：一个共享、长期有效、不区分人的 token 一旦暴露在公网，就等于绕过了账号体系。
- 脚本 / CI 调 API 的需求放到后续批次做**个人 API Token**（每人可建多个、可吊销、哈希存库、actor 记到个人名下）。

### 2.10 前端改动

- 新增登录页 `/login`（用户名、密码、错误提示、锁定提示），登录后回到原地址（`returnTo`）。
- `AuthGate` 改为：启动时 `GET /auth/me`，401 就跳登录页；`must_change_password` 时先进改密弹窗。
- 顶栏右上角用户菜单：显示名、修改密码、退出登录。
- 管理员可见“用户”页：列表、新建、重置密码、禁用、角色、解锁。
- `client.ts` / `sse.ts`：去掉 Bearer 头，加 `credentials: "same-origin"` 和写请求的 `X-CSRF-Token`；任何 401 统一跳登录页。`ArtifactImage` 可以保留 fetch，也可改回 `<img src>`。
- 删除 `token.ts` 及其测试。

---

## 3. 把 `local-user` 换成真实用户

**做法（便宜）**：新增 `testagent/core/actor.py`，里面一个 `ContextVar current_actor`。认证中间件验完会话后设成用户名；27 处默认值从 `"local-user"` 改成 `None`，在 `BaseService.__init__`（以及几个不继承它的 Service）里 `self.actor = actor or current_actor.get()`。路由层一行都不用改。后台线程没有请求上下文，默认值是 `"system"`，现有显式传 `system` / `scheduler` 的地方保持不变。`automation.py` 里写死的 `actor="local-user"` 改成 `self.actor`。

> 注意：`BaseHTTPMiddleware` 下 ContextVar 能传到路由（同一个任务上下文），同步路由跑在线程池里也会复制上下文；实现时写测试确认。

| 范围 | 内容 |
|---|---|
| **本批做** | 审计 `actor`；需求/策略 `confirmed_by`、建议 `decided_by`、手工执行 `executed_by`、模型评审 `reviewed_by`、缺陷 `created_by_actor`、报告/学习 `created_by`；用户手动点 Run 时在 job payload 里记 `requested_by`（若运行表已有触发人字段就写进去，实现时确认）；界面上显示 actor 时用显示名 |
| **推迟** | 需求里的“角色/负责人”、缺陷自动指派的责任人和真实账号对应；按被测系统/项目的成员权限；人员统计（people stats）按账号聚合；个人 API Token；SSO/LDAP/OIDC、二次验证、邮件找回密码；审计日志查询页；多实例会话存储 |

服务器数据会清空，历史 `local-user` 记录无需迁移；本机旧库里的 `local-user` 原样保留，界面显示为“local-user（旧）”。

---

## 4. 公网暴露

### 4.1 拓扑

```
浏览器 ──443/HTTPS──▶ Caddy(proxy) ──compose 内网 http──▶ testagent:8765 ──内网──▶ demo:8766
                                                          ▲                      ▲
                                  宿主机 127.0.0.1:8765（SSH 隧道备用）   宿主机 127.0.0.1:8766（仅调试）
```

- 只有 Caddy 发布到公网端口（443）。`testagent` 和 `demo` 继续只绑 `127.0.0.1`，Caddy 只反代 testagent，**demo 不经代理、不开安全组**。
- 平台侧：`uvicorn.run(..., proxy_headers=True, forwarded_allow_ips=TESTAGENT_TRUSTED_PROXIES)`，这样 `request.base_url` 变成 `https://<公网IP>`，现有 Origin 校验和 Secure Cookie 才正确；compose 里设 `TESTAGENT_ALLOWED_HOSTS=${TESTAGENT_PUBLIC_HOST}`。

### 4.2 docker-compose 增量（示意）

```yaml
  proxy:
    image: caddy:2-alpine            # 实现时钉具体版本（≥2.10，支持 ACME profile）
    profiles: ["public"]             # .env 里 COMPOSE_PROFILES=public 才启动，本机用户不受影响
    depends_on: [testagent]
    ports:
      - "443:443"
    environment:
      TESTAGENT_PUBLIC_HOST: ${TESTAGENT_PUBLIC_HOST:?set TESTAGENT_PUBLIC_HOST}
    volumes:
      - ./ops/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data             # 证书和内部 CA，必须持久化
      - caddy-config:/config
    restart: unless-stopped
```

`ops/Caddyfile`（主方案：IP + 内部证书）：

```
{
	auto_https disable_redirects   # 不监听 80
	default_sni {$TESTAGENT_PUBLIC_HOST}   # 直接用 IP 访问时浏览器不发 SNI
}
https://{$TESTAGENT_PUBLIC_HOST} {
	tls internal
	encode gzip
	request_body { max_size 20MB }
	header {
		X-Content-Type-Options nosniff
		X-Frame-Options DENY
		Referrer-Policy same-origin
		-Server
	}
	reverse_proxy testagent:8765     # SSE 响应 Caddy 会自动即时刷新
}
```

### 4.3 证书方案

| 方案 | 条件 | 体验 | 建议 |
|---|---|---|---|
| **A. 公网 IP + Caddy 内部证书**（主方案） | 只开 443 | 浏览器首次提示“不安全”，点继续即可；想去掉提示可把 Caddy 根证书（`caddy-data` 里的 `pki/authorities/local/root.crt`）导入 Windows“受信任的根证书颁发机构” | **本批默认** |
| B. 公网 IP + Let's Encrypt IP 证书 | Let's Encrypt 自 2026-01-15 起正式签发 IP 证书，仅限 6 天短期证书（`profile shortlived`），Caddy 自动续期；443 必须**对全网开放**供验证（TLS-ALPN） | 浏览器无警告 | 可选开关 `TESTAGENT_TLS=acme`；代价是 443 不能只放行你自己的 IP，且服务器要能访问 Let's Encrypt |
| C. 域名 + Let's Encrypt | 域名 A 记录指向服务器 + **ICP 备案** | 最好 | 有备案域名后再做；Caddyfile 只需把站点地址换成域名、去掉 `tls internal` |
| D. 高端口（如 8443） | — | 同 A | 不推荐：端口不改变备案义务，也不比 443 安全，只是多一个要记的端口 |

**关于 ICP 备案（已查阿里云官方帮助中心）**：
- 域名解析到**阿里云中国内地**服务器提供网站服务，必须先在阿里云完成 ICP 备案，否则阿里云会**阻断该域名的访问**；**用非 80/443 端口也一样要备案**，端口不改变备案义务。
- 阻断是按域名识别的；阿里云的排障文档也写到“域名未备案时域名访问被拦、IP 访问不受影响”。所以**方案 A/B 用 IP 访问不会被这套拦截挡住**。但法规层面“内地服务器对外提供网站服务需备案”是原则性要求，本方案定位为“少数人、需登录的内部工具”，不对外公开推广；这是常见做法，但不构成法律意见。
- 备案要求：内地节点、包年包月且累计 ≥3 个月、有公网带宽的 ECS（按量付费和免费试用不行）。不想备案又要域名，可以把服务器换到中国香港/海外节点（无需 ICP，但需公安备案）。
- 来源：help.aliyun.com/zh/icp-filing/not-for-the-record-dns-can-access-to-different-areas ；help.aliyun.com/zh/icp-filing/basic-icp-service/user-guide/icp-filing-server-access-information-check ；developer.aliyun.com/article/767597 ；letsencrypt.org/2026/01/15/6day-and-ip-general-availability.html

### 4.4 阿里云安全组（入方向）

| 端口 | 来源 | 说明 |
|---|---|---|
| **TCP 443** | 建议只放你常用的公网 IP/网段；全网 `0.0.0.0/0` 也可以（有登录+限速），用方案 B 时必须全网 | 唯一新增规则 |
| TCP 22 | 只放你的 IP | 保持现状，SSH 隧道仍可作备用通道 |
| 80 / 8765 / 8766 / 5432 | **不开** | 8765/8766 本来就只绑 127.0.0.1；数据库不发布端口 |

另外：Docker 发布的端口会绕过 ufw，所以“只绑 127.0.0.1 + 安全组只开 443”才是真正的边界，不要把 `ports` 改成 `0.0.0.0`。

---

## 5. 服务器升级步骤（写进 `docs/deployment.md`）

```bash
cd <服务器上的 testagent 目录>
git pull

# 编辑 .env（chmod 600 .env；里面有密码，不要提交、不要贴到聊天里）
#   COMPOSE_PROFILES=public
#   TESTAGENT_PUBLIC_HOST=<服务器公网IP>
#   TESTAGENT_ADMIN_USER=<管理员用户名>
#   TESTAGENT_ADMIN_PASSWORD=<至少10位>     # 首次登录成功后可删掉
#   删除 TESTAGENT_ACCESS_TOKEN（已不再使用）
```

二选一：

- **保留数据升级**（迁移 0022 自动执行，原有数据都在）：
  ```bash
  docker compose up -d --build
  ```
- **清空重来**（⚠️ 不可恢复：删除 `pgdata`、`demo-data`、`testagent-data` 三个卷，包括数据库、测试仓库、截图、日志，以及界面里配置的模型 API Key `secrets.json`，之后要重新在 Agent 设置里填）：
  ```bash
  docker compose down -v
  docker compose up -d --build
  ```

然后：
1. 阿里云控制台 → 安全组 → 入方向 → 添加 TCP 443（来源见 §4.4）。
2. 浏览器打开 `https://<公网IP>/`，首次证书提示点“继续访问”（或导入 Caddy 根证书），用管理员登录。
3. 检查：`docker compose ps` 四个服务健康；`docker compose logs proxy` 无证书错误；`curl -k https://<公网IP>/api/v1/health` 返回 ok；从外网访问 `http://<公网IP>:8765`、`:8766` 应该连不上。
4. 在“用户”页给其他人建账号（首次登录强制改密）。

---

## 6. 测试、文档、工作量

### 6.1 新增/修改的测试

后端（pytest，需 Postgres 测试库）：
- 单元：argon2 哈希/校验/rehash；密码规则；锁定计数和解锁时间；Cookie 属性（HttpOnly/Secure/SameSite/`__Host-`）；CSRF 比对；IP 限速令牌桶；`current_actor` 在同步/异步路由里都生效。
- 接口：登录成功/失败（通用错误、计时防枚举）；连续 5 次失败锁定、管理员解锁；每 IP 限速 429；登出后旧 Cookie 401；过期会话 401；改密码后其它会话失效；禁用用户立即失效；member 调 `/users`、Agent 设置、环境命令 → 403；不能禁用最后一个 admin；缺 `X-CSRF-Token` 或 Origin 不符 → 403；SSE 流用 Cookie 能连上、未登录 401；actor 记录（确认需求、手工执行、审计行 = 用户名，后台任务 = system）。
- 启动：用户表为空时按环境变量建 admin、非空时忽略；设了 `TESTAGENT_ACCESS_TOKEN` 只告警不生效；本机票据只能用一次、2 分钟过期、非回环请求拒绝；`proxy_headers` 下 `base_url` 为 https。
- CLI：`user add/passwd/list/unlock/disable`。
- 迁移：空库一路迁到 0022、0021 库升级到 0022。
- 现有测试：`tests/conftest.py` 改成建测试用户并登录（拿 Cookie + CSRF），另外 3 个引用 token 的测试文件和 `test_auth_api.py`、`test_launch_settings.py` 相应更新。

前端（vitest）：登录页；401 跳转并带 `returnTo`；写请求自动带 `X-CSRF-Token`；用户菜单与改密；用户管理页；删掉 token 相关测试（`AgentToolsPage`、`ReportPage`、`taskBinding` 等测试里的 token 桩）。

E2E / 冒烟：Playwright 走一遍“登录 → 打开演示被测系统 → 退出”；`docker compose --profile public up` 后用 curl 验证 443 可用、`/` 未登录跳登录页、demo 不可经代理访问。

### 6.2 要更新的文档

- `README.md` / `README.zh.md`：快速开始改为设置管理员、用账号登录；新增“公网访问”小节链接到部署文档；去掉 `grep "Sign in"`。
- `.env.example`：新增 `TESTAGENT_ADMIN_USER`、`TESTAGENT_ADMIN_PASSWORD`、`TESTAGENT_PUBLIC_HOST`、`COMPOSE_PROFILES`、`TESTAGENT_TLS`、`TESTAGENT_TRUSTED_PROXIES`、会话时长；删除 `TESTAGENT_ACCESS_TOKEN`。
- `docker-compose.yml` 顶部注释；新增 `ops/Caddyfile`。
- `docs/deployment.md`：公网部署、证书三方案、ICP 说明、安全组、§5 升级/清空、导入根证书、忘记密码（CLI）。
- `examples/procurement/README.md`（演示流程）以及演示手册：登录步骤替换掉 token/SSH 隧道步骤。
- `SECURITY.md`：威胁模型（登录用户可在容器内执行代码）、建议限制 443 来源。
- `CHANGELOG.md`：0.2.0 —— 账号登录、公网 HTTPS、移除共享 token（破坏性变更）。
- `docs/third-party-licenses.md`：argon2-cffi。
- 路线图 `team-readiness-roadmap-t33u.md`：用户体系第一步标记为进行中。

### 6.3 工作量

| 部分 | 人日 |
|---|---|
| 迁移 + 账号/会话/CSRF/限速 + 中间件 + 接口 + CLI + 启动引导 + actor 替换 | 1.5 |
| 前端：登录页、AuthGate、用户菜单、改密、用户管理、client/sse 改造 | 1 |
| Caddy/compose/代理头 + 服务器冒烟 | 0.5 |
| 测试补齐与现有测试改造 | 0.5–1 |
| 文档 | 0.5 |
| **合计** | **约 3.5–4** |

---

## 7. 在哪个仓开发（建议）

核对结果：
- 开发仓 `D:\CodeWork\TestAgent\ontology-test-platform`（HEAD 81ae563）：**界面和代码里仍有约 2800 行中文**，**没有** `Dockerfile` / `docker-compose.yml`；迁移同样到 0021。
- 发布仓 `D:\CodeWork\TestAgent\release\testagent`（HEAD 8d9f36e）：已英文化、有 Docker、是公开仓，服务器部署的就是它；源码里没有中文。

**建议：从本批起，发布仓就是唯一主线**，所有改动在发布仓开分支开发、测试、合并、推送，服务器 `git pull` 即可。开发仓冻结为历史存档（不再改代码，`specs\` 设计文档照旧放在 `D:\CodeWork\TestAgent\specs\`）。理由：两边结构已经分叉（英文化、Docker、包名/路径），继续双写必然漏改；用户实际部署和对外发布的都是发布仓。
（另：box 上的副本 `/workspace/t26/rel` 停在较早的提交，开工前需重新同步。）

---

## 8. 需要你确认的问题

1. **多少人用、都是谁？** 都是信任的人吗？（任何登录用户都能在容器里执行代码，见 §2.7）
2. **443 的来源**：只放你自己的 IP（更安全，但只能用方案 A 自签证书），还是全网开放？
3. **证书**：接受首次“不安全”提示/导入根证书（方案 A），还是愿意 443 全网开放换取无警告的 Let's Encrypt IP 证书（方案 B）？
4. **member 权限**：Agent 设置（模型 Key）和环境启动命令只给 admin，可以吗？
5. **会话时长**：闲置 12 小时、最长 7 天，可以吗？
6. **旧 token**：直接移除、脚本 API Token 以后再做，可以吗？还是现在就需要给脚本/CI 用？
7. **本机桌面模式**：保留“启动器一键登录”（一次性票据），可以吗？
8. **仓库**：同意发布仓作为唯一主线、开发仓冻结吗？
9. 以后是否打算买域名并做 ICP 备案（或者把服务器换到香港节点）？这决定要不要提前做方案 C 的开关。
