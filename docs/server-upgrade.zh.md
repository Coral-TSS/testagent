# 服务器升级指南：公网 HTTPS + 账号登录（阿里云 ECS）

适用于已经用 Docker Compose 部署了 TestAgent v0.1 的服务器（之前要靠 SSH 隧道和日志里的 `#t=` 令牌登录）。
升级后：浏览器直接打开 `https://<服务器公网IP>/`，用账号密码登录；不需要域名，也不需要 SSH 隧道。

> 下面的 `<服务器公网IP>`、`<管理员用户名>`、`<管理员密码>` 都换成你自己的值。密码只写在服务器的 `.env`
> 里，不要提交到 git，也不要贴到聊天或工单里。

## 1. 阿里云控制台：安全组（先做）

ECS 控制台 → 实例 → 安全组 → **入方向** → 手动添加：

| 授权策略 | 协议/端口 | 授权对象 | 说明 |
|---|---|---|---|
| 允许 | **TCP 443** | **0.0.0.0/0** | 唯一需要新开的端口 |

- **为什么 443 要对所有地址开放**：证书用 Let's Encrypt 的 IP 证书，验证方式是 **TLS-ALPN-01，走 443 端口**，
  Let's Encrypt 会从互联网上多个地点来连 443。所以 **不需要开 80**（80 只在 HTTP-01 验证时才用，我们没用）。
- **不要开**：80、8765、8766、5432。8765/8766 本来就只绑定在 `127.0.0.1`，数据库端口不对外发布。
- 22（SSH）保持现状，最好只放你自己的 IP。
- 服务器要能**出网**访问 Let's Encrypt（`acme-v02.api.letsencrypt.org:443`），默认安全组出方向全放行即可。
- 如果服务器上开了 ufw：`sudo ufw allow 443/tcp`。

## 2. 拉代码、改 .env

```bash
cd <服务器上的 testagent 目录>
git pull
chmod 600 .env
nano .env      # 或 vim
```

在 `.env` 里加上（已有的 `POSTGRES_PASSWORD` 等保持不变）：

```ini
COMPOSE_PROFILES=public
TESTAGENT_PUBLIC_HOST=<服务器公网IP>
TESTAGENT_TLS=acme
TESTAGENT_ADMIN_USER=<管理员用户名>        # 小写字母/数字/._-，2–32 位
TESTAGENT_ADMIN_PASSWORD=<管理员密码>      # 至少 10 位
```

并**删除** `TESTAGENT_ACCESS_TOKEN` 这一行（新版本不再使用，留着只会在日志里告警）。

## 3. 启动（二选一）

**A. 保留现有数据升级（推荐）**：数据库迁移 0022 会自动执行，原有 SUT、需求、用例、执行记录都还在。

```bash
docker compose up -d --build
```

**B. 清空重来**：⚠️ **不可恢复**。会删除所有数据卷：数据库（`pgdata`）、测试脚本仓库/截图/日志和
**Agent 设置里的模型 API Key**（`testagent-data`）、演示系统数据（`demo-data`）、证书（`caddy-data`）。
之后需要重新在 Agent settings 里填模型地址和 Key。

```bash
docker compose down -v
docker compose up -d --build
```

> 不要频繁执行 B：每次清空都会重新申请证书，Let's Encrypt 对同一个 IP 每 7 天最多签发 5 张。

## 4. 检查

```bash
docker compose ps                                  # db、demo、testagent 健康，proxy 运行中
docker compose logs proxy | grep -i "certificate obtained"
docker compose logs testagent | grep -i "first admin"
curl -s https://<服务器公网IP>/api/v1/health      # {"status":"ok",...}
```

在你自己的电脑上，`http://<服务器公网IP>:8765` 和 `:8766` 应该**连不上**（正常现象：只有 443 对外）。

## 5. 第一次登录

1. 浏览器打开 `https://<服务器公网IP>/`（地址栏是锁形图标，不会有证书警告）。
2. 用 `.env` 里的管理员用户名和密码登录。
3. 登录成功后，可以把 `.env` 里的 `TESTAGENT_ADMIN_PASSWORD` 删掉（账号已经存在，这个变量不会再被使用），
   然后执行一次 `docker compose up -d`。
4. 左侧菜单 **Users** → **New user** 给其他人建账号：设一个初始密码当面告诉对方，对方首次登录必须改密码。
5. 右上角账号按钮里可以 **Change password** 和 **Sign out**。
6. 如果选了清空重来（3B），在 **Agent settings** 重新填模型地址、模型名和 API Key。

权限：只有 admin 能管理账号、修改 Agent 设置（模型 Key）、修改环境的启动命令；member 可以做测试流程里的其他所有操作。
所有登录的人都能让平台在容器里执行测试脚本，所以只给信任的人开账号。

## 6. 出问题时

| 现象 | 处理 |
|---|---|
| 打不开 `https://<IP>` | 确认安全组入方向 TCP 443 已放行 `0.0.0.0/0`；`docker compose ps proxy`；`docker compose logs proxy` |
| 日志里证书申请失败（challenge failed / timeout） | 多半是 443 没对外开放，或服务器不能出网。临时改用自签名证书：`.env` 里设 `TESTAGENT_TLS=internal`，`docker compose up -d`；浏览器会提示“不安全”，点“继续访问”，或导入根证书：`docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt`，在 Windows 里导入“受信任的根证书颁发机构” |
| 登录页显示 “No account yet” | `.env` 里管理员变量没生效：检查拼写后 `docker compose up -d`，或 `docker compose exec testagent testagent user add <管理员用户名> --admin` |
| 忘记密码 / 账号被锁（连续 5 次输错锁 15 分钟） | `docker compose exec testagent testagent user passwd <用户名>`（同时解锁）或 `... user unlock <用户名>` |
| “This address is not configured for the platform” | `.env` 里的 `TESTAGENT_PUBLIC_HOST` 和你访问的地址不一致，改好后 `docker compose up -d` |

SSH 隧道（`127.0.0.1:8765`）仍然可以用作备用入口。

## 关于域名和备案

- 现在用 IP + Let's Encrypt IP 证书，不需要域名。
- 以后如果要用域名：服务器在阿里云**中国内地**节点时，域名必须先完成 **ICP 备案**，否则阿里云会阻断该域名的访问，
  换成非 80/443 端口也一样。备案后把 `TESTAGENT_PUBLIC_HOST` 改成域名、添加 A 记录指向服务器即可。
