# Deployment guide

TestAgent is a **single-user, local** web application: a FastAPI backend that also serves the built
React UI, a PostgreSQL 17 database, and a local git repository per system under test (SUT) for the
generated scripts. There are two ways to run it:

- [Docker Compose](#docker-compose) is the easiest and works the same on Windows, macOS and Linux.
- [Local development](#local-development) is for hacking on the code.

> **Security model.** v0.1 has no user accounts. Access is protected by an access token, and requests
> are only accepted for `localhost` host names unless you allow more (see `TESTAGENT_ALLOWED_HOSTS`).
> Do not expose the platform to the internet.

---

## Docker Compose

### Requirements

- Docker Engine 24+ (or Docker Desktop) with Compose v2 (`docker compose version`)
- About 2.5 GB free disk space (the image is ~1.8 GB because it bundles Chromium for browser tests)

### Start

```bash
cp .env.example .env          # edit POSTGRES_PASSWORD; optionally TESTAGENT_ACCESS_TOKEN
docker compose up -d --build  # first build takes a few minutes
docker compose ps             # all three services should become "healthy"
```

| Service | What | URL on your machine |
|---|---|---|
| `testagent` | the platform (UI + API + worker + scheduler) | http://localhost:8765 |
| `demo` | the procurement demo SUT (with 3 seeded bugs) | http://localhost:8766 |
| `db` | PostgreSQL 17 | not published (internal only) |

Ports are bound to `127.0.0.1` only.

### Sign in

The UI needs an access token, passed in the URL fragment (`#t=…`, never sent to the server logs).

- **Random token (default)**: a new token is generated at every start and the sign-in link is printed:

  ```bash
  docker compose logs testagent | grep "Sign in"
  # [TestAgent] Sign in: http://localhost:8765/#t=3f9c…
  ```

- **Fixed token**: set `TESTAGENT_ACCESS_TOKEN` in `.env` (for example `openssl rand -hex 24`), then
  open `http://localhost:8765/#t=<your token>`. Restart with `docker compose up -d`.

The browser keeps the token for the session; if it expires, open the sign-in link again.

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
| `TESTAGENT_ACCESS_TOKEN` | random | Fixed sign-in token |
| `TESTAGENT_ALLOWED_HOSTS` | empty | Extra host names accepted besides `localhost` / `127.0.0.1`, comma separated (e.g. `testagent.lan`) |
| `TESTAGENT_TIMEZONE` | `UTC` | IANA time zone for schedules and displayed times (e.g. `Europe/Berlin`) |
| `TESTAGENT_AGENT_LANGUAGE` | `English` | Language of the text the agent writes (requirements, cases, reports) |
| `TESTAGENT_SEED_DEMO` | `1` | Create the demo SUT (model, APIs, people, environment) on first start |
| `PROCUREMENT_DEMO_BUGS` | `1` | Seeded bugs in the demo SUT on (`1`) or off (`0`) |
| `DEBIAN_MIRROR` | `deb.debian.org` | Debian mirror used while building the image |

Platform settings available in all modes (prefix `TESTAGENT_`): `DATABASE_URL`, `TEST_DATABASE_URL`,
`RUNTIME_DIR`, `HOST`, `PORT`, `ACCESS_TOKEN`, `ALLOWED_HOSTS`, `DEMO_URL`, `TIMEZONE`,
`AGENT_LANGUAGE`, `BROWSER_HEADLESS` (default `true`), `PYTEST_TIMEOUT_S` (default `300`),
`ARTIFACT_MAX_BYTES` (default 50 MB).

### Testing your own application

Add a SUT in the UI and create an **environment** with the base URL of your app *as seen from the
`testagent` container*:

- an app on your host machine: `http://host.docker.internal:<port>` (Docker Desktop; on Linux add
  `extra_hosts: ["host.docker.internal:host-gateway"]` to the `testagent` service)
- another container: put it on the same Compose network and use its service name
- a remote test environment: its normal URL

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

### Stop and remove

```bash
docker compose down        # keeps the volumes (your data)
docker compose down -v     # also deletes all data
```

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
uv run testagent                 # migrates, opens the browser signed in, starts the demo SUT
uv run testagent --no-browser    # prints the sign-in link instead
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
| "Sign-in required" page | Open the sign-in link from `docker compose logs testagent`, or set `TESTAGENT_ACCESS_TOKEN`. |
| "The platform only accepts local connections" when opening via an IP or host name | Add it to `TESTAGENT_ALLOWED_HOSTS` and publish the port on that interface (change `127.0.0.1:8765:8765`). Only do this on a trusted network. |
| `testagent` keeps restarting with "Cannot connect to the database" | Check `docker compose logs db`; if you changed `POSTGRES_PASSWORD` after the first start, the old password is still stored in the `pgdata` volume. |
| AI buttons say the model is not configured | Fill in **Agent settings** and click *Test connection*. |
| "SUT environment … cannot be reached" | The environment URL must be reachable from the platform (inside Docker use `host.docker.internal` or a service name, not `localhost`). |
| `apt-get` fails during `docker build` | Use another mirror: `DEBIAN_MIRROR=<mirror host> docker compose build`. |
| Browser executions fail to launch Chromium (local) | Run the Playwright install command above with `PLAYWRIGHT_BROWSERS_PATH=0`. |
| "Another platform instance is already running" | Only one instance per database; stop the other one. |
