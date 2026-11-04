# Deployment guide

TestAgent is a web application for a **small, trusted team**: a FastAPI backend that also serves the
built React UI, a PostgreSQL 17 database, and a local git repository per system under test (SUT) for the
generated scripts. There are three ways to run it:

- [Docker Compose](#docker-compose) is the easiest and works the same on Windows, macOS and Linux.
- [Public access (HTTPS)](#public-access-https) adds a Caddy proxy for a server reachable from the internet.
- [Local development](#local-development) is for hacking on the code.

> **Security model.** Everyone signs in with an account (roles `admin` / `member`). Requests are only
> accepted for `localhost`, `TESTAGENT_PUBLIC_HOST` and `TESTAGENT_ALLOWED_HOSTS`. Every signed-in user
> can effectively run code in the platform container (generated test scripts), so only give accounts to
> people you trust. See [SECURITY.md](../SECURITY.md).

---

## Docker Compose

### Requirements

- Docker Engine 24+ (or Docker Desktop) with Compose v2 (`docker compose version`)
- About 2.5 GB free disk space (the image is ~1.8 GB because it bundles Chromium for browser tests)

### Start

```bash
cp .env.example .env          # edit POSTGRES_PASSWORD, TESTAGENT_ADMIN_USER, TESTAGENT_ADMIN_PASSWORD
docker compose up -d --build  # first build takes a few minutes
docker compose ps             # all three services should become "healthy"
```

| Service | What | URL on your machine |
|---|---|---|
| `testagent` | the platform (UI + API + worker + scheduler) | http://localhost:8765 |
| `demo` | the procurement demo SUT (with 3 seeded bugs) | http://localhost:8766 |
| `db` | PostgreSQL 17 | not published (internal only) |

Ports are bound to `127.0.0.1` only.

### Sign in and accounts

- **First admin.** Set `TESTAGENT_ADMIN_USER` and `TESTAGENT_ADMIN_PASSWORD` (at least 10 characters)
  in `.env` before the first start. The account is created only while there are no accounts at all;
  later changes to these variables are ignored, and you can remove the password from `.env` after the
  first sign-in. The password is never printed.
- **More people.** An admin opens **Users** (left menu) → **New user** and sets an initial password; the
  user must choose a new one at the first sign-in. Admins can change roles, reset passwords (signs the
  user out everywhere), unlock and disable accounts. Accounts are never deleted, so history keeps its
  names.
- **Roles.** `member` can do everything in the test workflow. Only `admin` can manage accounts, change
  the agent model settings (endpoint and API key) and set or change an environment's start command
  (it runs on the platform host).
- **Sessions.** An HttpOnly cookie (`Secure` over HTTPS, `SameSite=Lax`); writes also carry a CSRF
  token. A session ends after 12 idle hours and after 7 days at the latest
  (`TESTAGENT_SESSION_IDLE_HOURS`, `TESTAGENT_SESSION_MAX_DAYS`). Changing your password signs out your
  other sessions.
- **Brute force.** At most 10 sign-in attempts per minute (100 per hour) per client address; 5 wrong
  passwords in a row lock the account for 15 minutes (an admin can unlock it earlier).
- **Command line** (first admin without `.env`, forgotten passwords; prompts for the password):

  ```bash
  docker compose exec testagent testagent user add <name> --admin
  docker compose exec testagent testagent user passwd <name>     # also unlocks, signs out everywhere
  docker compose exec testagent testagent user list
  docker compose exec testagent testagent user unlock|disable|enable <name>
  ```

Who did what (confirmations, manual results, defects, the change log) is recorded under the user name;
background work (worker, scheduler, agent) appears as `system`, `scheduler` or `agent:…`.

### Configure the model

In the UI open **Agent settings** and enter an OpenAI-compatible endpoint:

| Provider | Base URL | Model (example) |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Local (Ollama, vLLM, LM Studio, …) | e.g. `http://host.docker.internal:11434/v1` | your model |

Click **Test connection**. The API key is stored in `/data/runtime/secrets.json` inside the
`testagent-data` volume (file mode 600; DPAPI-encrypted on Windows when running locally). It is never
written to the database or logs, and the UI only shows a mask.

### Environment variables

Set them in `.env` (Compose substitutes them) or in `docker-compose.yml`.

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_PASSWORD` | (required) | Password of the bundled database |
| `TESTAGENT_PORT` | `8765` | Host port of the UI |
| `TESTAGENT_ADMIN_USER` / `TESTAGENT_ADMIN_PASSWORD` | empty | First admin, created only while there are no accounts |
| `COMPOSE_PROFILES` | empty | `public` also starts the HTTPS proxy (see [Public access](#public-access-https)) |
| `TESTAGENT_PUBLIC_HOST` | empty | Public IP (or domain) the proxy serves; also an accepted host name |
| `TESTAGENT_TLS` | `acme` | `acme` = Let's Encrypt (IP: 6-day certificate, TLS-ALPN-01 on 443); `internal` = Caddy's own CA |
| `TESTAGENT_SESSION_IDLE_HOURS` / `TESTAGENT_SESSION_MAX_DAYS` | `12` / `7` | Session lifetime |
| `TESTAGENT_ALLOWED_HOSTS` | empty | Extra host names accepted besides `localhost` / `127.0.0.1` / `TESTAGENT_PUBLIC_HOST`, comma separated (e.g. `testagent.lan`) |
| `TESTAGENT_TIMEZONE` | `UTC` | IANA time zone for schedules and displayed times (e.g. `Europe/Berlin`) |
| `TESTAGENT_AGENT_LANGUAGE` | `English` | Language of the text the agent writes (requirements, cases, reports) |
| `TESTAGENT_SEED_DEMO` | `1` | Create the demo SUT (model, APIs, people, environment) on first start |
| `PROCUREMENT_DEMO_BUGS` | `1` | Seeded bugs in the demo SUT on (`1`) or off (`0`) |
| `DEBIAN_MIRROR` | empty (`deb.debian.org`) | Debian mirror host used while building the image (see [Package mirrors](#package-mirrors-for-the-build)) |
| `PIP_INDEX_URL` / `NPM_REGISTRY` / `PLAYWRIGHT_DOWNLOAD_HOST` | empty | Python index, npm registry and Chromium download host used while building the image |
| `UV_IMAGE` | `ghcr.io/astral-sh/uv:0.13` | Image the `uv` binary is copied from |
| `PYTHON_IMAGE` / `NODE_IMAGE` | `python:3.12-slim-bookworm` / `node:22-bookworm-slim` | Base images (for a registry proxy) |

Platform settings available in all modes (prefix `TESTAGENT_`): `DATABASE_URL`, `TEST_DATABASE_URL`,
`RUNTIME_DIR`, `HOST`, `PORT`, `ADMIN_USER`, `ADMIN_PASSWORD`, `ALLOWED_HOSTS`, `DEMO_URL`, `TIMEZONE`,
`AGENT_LANGUAGE`, `BROWSER_HEADLESS` (default `true`), `PYTEST_TIMEOUT_S` (default `300`),
`ARTIFACT_MAX_BYTES` (default 50 MB), `SESSION_IDLE_HOURS`, `SESSION_MAX_DAYS`, `COOKIE_SECURE`
(`auto`: `Secure` cookie over HTTPS), `TRUSTED_PROXIES` (whose `X-Forwarded-*` headers count; default
`127.0.0.1`, `*` in Docker Compose). `TESTAGENT_ACCESS_TOKEN` from v0.1 is no longer used (a warning is
logged if it is still set).

### Testing your own application

Add a SUT in the UI and create an **environment** with the base URL of your app *as seen from the
`testagent` container*:

- an app on your host machine: `http://host.docker.internal:<port>` (Docker Desktop; on Linux add
  `extra_hosts: ["host.docker.internal:host-gateway"]` to the `testagent` service)
- another container: put it on the same Compose network and use its service name
- a remote test environment: its normal URL

### Package mirrors for the build

`docker compose up -d --build` downloads Debian packages, Python packages, npm packages and
Playwright's Chromium. If that is slow (for example on a server in mainland China), set mirrors in
`.env`; all are empty by default, which means the official sources:

```ini
DEBIAN_MIRROR=mirrors.aliyun.com
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
NPM_REGISTRY=https://registry.npmmirror.com
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
```

Python and npm packages are still verified against the hashes in `uv.lock` and
`web/package-lock.json`. The base images (`python`, `node`, `postgres`, `caddy`) come from Docker Hub
and the `uv` binary from `ghcr.io`; if pulling them is slow, configure a registry mirror for the
Docker daemon (`"registry-mirrors"` in `/etc/docker/daemon.json`, then `systemctl restart docker`),
and if needed point `UV_IMAGE` at a proxy of `ghcr.io/astral-sh/uv:0.13`.

The build needs BuildKit (`docker buildx version`). Downloads are kept in BuildKit cache mounts, so
later builds only fetch what changed and a code-only change rebuilds in seconds; avoid
`docker builder prune` unless you need the disk space. Only Playwright's headless Chromium shell is
installed; build with `PLAYWRIGHT_ONLY_SHELL=0` for the full Chromium build. Per-step timing:
`docker compose build --progress=plain`.

### Data and volumes

| Volume | Contents |
|---|---|
| `pgdata` | PostgreSQL data (everything except the files below) |
| `testagent-data` | `/data/runtime`: model API key, local git test repos with generated scripts, screenshots, traces and other artifacts |
| `demo-data` | the demo SUT's SQLite database |

### Backup and restore

```bash
# database
docker compose exec -T db pg_dump -U testagent -Fc testagent > testagent-$(date +%F).dump
# runtime files (test repos, artifacts, secrets)
docker run --rm -v testagent_testagent-data:/data -v "$PWD":/backup busybox \
  tar czf /backup/testagent-runtime-$(date +%F).tgz -C /data .

# restore the database into an empty stack
docker compose up -d db
docker compose exec -T db pg_restore -U testagent -d testagent --clean --if-exists < testagent-YYYY-MM-DD.dump
```

The volume names are prefixed with the Compose project name (`testagent_` by default).

### Upgrade

```bash
docker compose exec -T db pg_dump -U testagent -Fc testagent > before-upgrade.dump   # always back up first
git pull
docker compose up -d --build
```

Database migrations run automatically when the platform starts. Downgrades are not supported; restore
the backup instead.

**From v0.1:** the shared access token is gone. Before `docker compose up -d --build`, add
`TESTAGENT_ADMIN_USER` / `TESTAGENT_ADMIN_PASSWORD` to `.env` (and remove `TESTAGENT_ACCESS_TOKEN`); for
public HTTPS also see [Public access](#public-access-https). A Chinese step-by-step guide for a cloud
server is in [server-upgrade.zh.md](server-upgrade.zh.md).

### Stop and remove

```bash
docker compose down        # keeps the volumes (your data)
docker compose down -v     # also deletes all data (cannot be undone)
```

---

## Public access (HTTPS)

For a server that people reach over the internet (no domain needed). Only the `proxy` service (Caddy)
is published, on port **443**; `testagent` stays on `127.0.0.1:8765` and the demo SUT on
`127.0.0.1:8766` (the platform reaches it as `http://demo:8766` inside the Compose network).

```
browser ──HTTPS 443──▶ proxy (Caddy) ──▶ testagent:8765 ──▶ demo:8766   (internal network only)
```

1. In `.env`:

   ```ini
   COMPOSE_PROFILES=public
   TESTAGENT_PUBLIC_HOST=203.0.113.10     # your server's public IP
   # TESTAGENT_TLS=acme                   # default; "internal" = self-signed fallback
   TESTAGENT_ADMIN_USER=<admin name>
   TESTAGENT_ADMIN_PASSWORD=<at least 10 characters>
   ```

2. Firewall / cloud security group: allow inbound **TCP 443** from anywhere (Let's Encrypt validates
   from several places on the internet). Do not open 80, 8765, 8766 or 5432.
3. `docker compose up -d --build`, then open `https://203.0.113.10/` and sign in.

**Certificates.**

| `TESTAGENT_TLS` | What you get | Needs |
|---|---|---|
| `acme` (default) | A browser-trusted Let's Encrypt certificate for the IP address. IP certificates are only issued with the 6-day `shortlived` profile; Caddy renews them automatically (about every 2–3 days). Validation uses **TLS-ALPN-01 on port 443**, so port 80 stays closed. | 443 reachable from the internet; outbound HTTPS to Let's Encrypt; the `caddy-data` volume kept (rate limits) |
| `internal` | Caddy's own CA: works offline and behind any firewall, but the browser warns until you trust the root certificate. | nothing |

With `internal`, copy the root certificate and import it into your OS / browser trust store
(Windows: *Trusted Root Certification Authorities*):

```bash
docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```

Check the certificate: `docker compose logs proxy | grep -i certificate`. If Let's Encrypt cannot reach
port 443 the log shows the failed challenge; fix the firewall or switch to `TESTAGENT_TLS=internal`
and run `docker compose up -d`.

**A domain later.** Point an A record at the server and set `TESTAGENT_PUBLIC_HOST=<domain>`; Caddy then
gets a normal certificate. On servers in mainland China a domain must have an ICP filing first, or the
cloud provider blocks it (also on other ports).

The SSH tunnel to `127.0.0.1:8765` keeps working as a fallback (plain HTTP on localhost).

---

## Local development

Works on Windows, macOS and Linux.

### Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ (for the UI)
- PostgreSQL 17 (a local install or `docker run -p 127.0.0.1:5432:5432 -e POSTGRES_PASSWORD=… postgres:17`)

### Setup

```bash
uv sync
cp .env.example .env
```

Edit `.env` and set at least:

```ini
TESTAGENT_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/testagent
TESTAGENT_TEST_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/testagent_test
```

`.env` is git-ignored. Never commit it.

```bash
uv run python ops/init_db.py      # creates testagent and testagent_test if missing
```

Install Chromium into the project environment (keeps it out of your global profile):

```bash
# macOS / Linux
PLAYWRIGHT_BROWSERS_PATH=0 uv run playwright install chromium
# Linux only, if system libraries are missing:
PLAYWRIGHT_BROWSERS_PATH=0 uv run playwright install --with-deps chromium
```

```powershell
# Windows PowerShell
$env:PLAYWRIGHT_BROWSERS_PATH="0"; uv run playwright install chromium
```

Build the UI and optionally seed the demo SUT:

```bash
cd web && npm ci && npm run build && cd ..
uv run python ops/seed_procurement.py
```

### Run

```bash
uv run testagent                 # migrates, opens the browser signed in (one-time ticket), starts the demo SUT
uv run testagent --no-browser    # no browser: sign in with an account (see "Sign in and accounts")
uv run testagent --no-env-start  # do not start SUT environments that have a start command
```

On Windows you can double-click `ops\start.cmd` (it builds the UI on first run; `ops\start.cmd -Rebuild`
rebuilds it after code changes). Only one platform instance may use a database at a time.

For UI development with hot reload, run `npm run dev` in `web/` (Vite proxies `/api` to port 8765).

### Tests and checks

```bash
uv run pytest -q                                  # backend, API and end-to-end tests (needs the test DB and Chromium)
uv run ruff check . && uv run ruff format --check .
cd web
npm run lint && npx tsc -b --noEmit && npm test && npm run build
```

The test suite only touches `TESTAGENT_TEST_DATABASE_URL` and refuses to run against a database whose
name does not end in `_test`.

### Resetting a SUT

```bash
uv run python ops/reset_sut_data.py --sut procurement                    # dry run
uv run python ops/reset_sut_data.py --sut procurement --apply --repo-archive ../archive/test-repo-procurement
```

This keeps the SUT and its environments, removes everything else for that SUT (after a `pg_dump`
backup, which needs `pg_dump` on `PATH`) and moves the old test repo to the archive folder.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `POSTGRES_PASSWORD` error from `docker compose` | Create `.env` from `.env.example` and set a password. |
| Sign-in page says "No account yet" | Set `TESTAGENT_ADMIN_USER` / `TESTAGENT_ADMIN_PASSWORD` and `docker compose up -d`, or `docker compose exec testagent testagent user add <name> --admin`. |
| Forgot the admin password / account locked | `docker compose exec testagent testagent user passwd <name>` (or `user unlock <name>`). |
| "This address is not configured for the platform" | Set `TESTAGENT_PUBLIC_HOST` (or add the name to `TESTAGENT_ALLOWED_HOSTS`) and `docker compose up -d`. |
| `https://<IP>` does not load / certificate error | `docker compose ps proxy`, `docker compose logs proxy`; check inbound TCP 443 in the security group; use `TESTAGENT_TLS=internal` if Let's Encrypt cannot reach the server. |
| `testagent` keeps restarting with "Cannot connect to the database" | Check `docker compose logs db`; if you changed `POSTGRES_PASSWORD` after the first start, the old password is still stored in the `pgdata` volume. |
| AI buttons say the model is not configured | Fill in **Agent settings** and click *Test connection*. |
| "SUT environment … cannot be reached" | The environment URL must be reachable from the platform (inside Docker use `host.docker.internal` or a service name, not `localhost`). |
| `apt-get` fails or downloads are slow during `docker build` | Set package mirrors in `.env` (see [Package mirrors](#package-mirrors-for-the-build)) and `docker compose build`. |
| Browser executions fail to launch Chromium (local) | Run the Playwright install command above with `PLAYWRIGHT_BROWSERS_PATH=0`. |
| "Another platform instance is already running" | Only one instance per database; stop the other one. |
