# Third-party licenses

TestAgent itself is licensed under the [Apache License 2.0](../LICENSE). It depends on third-party
packages that keep their own licenses. This inventory was generated for v0.1.0 from `uv.lock`
(runtime dependencies, `uv export --no-dev`) and `web/package-lock.json` (runtime dependencies,
`npm ls --omit=dev`). It is informational, not legal advice.

## Summary

- **No strong-copyleft runtime dependency** of the platform code. Everything is MIT, BSD, ISC,
  Apache-2.0, PSF or similar, with these notes:
- **psycopg, psycopg-binary, psycopg-pool: LGPL-3.0.** Used unmodified as separately installed
  libraries through their public API, which LGPL permits from an Apache-2.0 project. If you redistribute
  them (e.g. in the Docker image), keep their license notices and let users replace them, which they
  can because they are ordinary pip packages. `psycopg-binary` bundles `libpq` (PostgreSQL License) and
  OpenSSL (Apache-2.0).
- **certifi: MPL-2.0** (file-level copyleft, applies only to certifi's own files, used unmodified).
- **orjson: MPL-2.0 AND (Apache-2.0 OR MIT)** (transitive via LangSmith, unmodified).
- **text-unidecode: Artistic-1.0 OR GPL-2.0-or-later**, transitive via `python-slugify` ←
  `pytest-playwright`. Used unmodified under the Artistic License option.
- The web UI uses **97 npm runtime packages: 88 MIT, 8 ISC, 1 BSD-3-Clause** (d3 modules used by
  React Flow). No GPL/LGPL/AGPL.
- **No fonts, icon files or images from third parties are bundled.** Icons come from
  `@ant-design/icons` (MIT) as code; the UI uses the system font stack.
- **Development-only tools** (not shipped): pytest, ruff, httpx, jsonschema with `format-nongpl`
  extras, Vite, Vitest, ESLint, TypeScript, openapi-typescript (all permissive).

### Docker image

The image is built from `python:3.12-slim-bookworm` (Debian) and adds Debian packages (`git`, `tini`,
`ca-certificates` and the system libraries Chromium needs) plus Playwright's Chromium build. Debian
packages include GPL/LGPL software (e.g. git, glibc); this is normal for Linux images. If you **publish
the image**, you distribute those packages: their licenses are in `/usr/share/doc/*/copyright` inside
the image and the sources are available from Debian. Chromium is BSD-3-Clause with third-party
components (see `chrome://credits`). The `postgres:17` image is under the PostgreSQL License.

## Python runtime dependencies

| Package | Version | License |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| charset-normalizer | 3.5.2 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| croniter | 6.2.4 | MIT |
| distro | 1.9.0 | Apache-2.0 |
| fastapi | 0.162.0 | MIT |
| greenlet | 3.5.6 | MIT AND PSF-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpcore2 | 2.16.0 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| httpx2 | 2.16.0 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| jiter | 0.18.0 | MIT |
| jsonpatch | 1.38 | BSD-3-Clause |
| jsonpointer | 3.6 | BSD-3-Clause |
| langchain-core | 1.7.3 | MIT |
| langchain-openai | 1.7.3 | MIT |
| langchain-protocol | 0.0.20 | MIT |
| langgraph | 1.2.19 | MIT |
| langgraph-checkpoint | 4.3.1 | MIT |
| langgraph-checkpoint-postgres | 3.2.0 | MIT |
| langgraph-prebuilt | 1.1.1 | MIT |
| langgraph-sdk | 0.4.11 | MIT |
| langsmith | 0.14.16 | MIT |
| openai | 3.42.0 | Apache-2.0 |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| orjson | 3.13.0 | MPL-2.0 AND (Apache-2.0 OR MIT) |
| ormsgpack | 1.13.0 | Apache-2.0 OR MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| playwright | 1.64.1 | Apache-2.0 |
| pluggy | 1.7.0 | MIT |
| psycopg | 3.3.6 | LGPL-3.0-only |
| psycopg-binary | 3.3.6 | LGPL-3.0-only |
| psycopg-pool | 3.3.3 | LGPL-3.0-only |
| pydantic | 2.14.1 | MIT |
| pydantic-core | 2.50.1 | MIT |
| pydantic-settings | 2.16.2 | MIT |
| pyee | 14.0.0 | MIT |
| pygments | 2.21.0 | BSD-2-Clause |
| pytest | 9.2.0 | MIT |
| pytest-playwright | 0.10.0 | Apache-2.0 |
| python-dateutil | 3.0.0 | Apache-2.0 OR BSD-3-Clause |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-slugify | 9.1.3 | MIT |
| pyyaml | 6.0.3 | MIT |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| requests | 2.34.2 | Apache-2.0 |
| requests-toolbelt | 1.0.0 | Apache-2.0 |
| six | 1.17.0 | MIT |
| sniffio | 1.3.1 | MIT OR Apache-2.0 |
| starlette | 1.10.0 | BSD-3-Clause |
| tenacity | 9.2.1 | Apache-2.0 |
| text-unidecode | 1.3 | Artistic-1.0 OR GPL-2.0-or-later |
| tiktoken | 0.14.0 | MIT |
| truststore | 0.10.5 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| tzdata | 2026.6 | Apache-2.0 |
| urllib3 | 2.8.0 | MIT |
| uuid-utils | 0.19.0 | BSD-3-Clause |
| uvicorn | 0.54.0 | BSD-3-Clause |
| websockets | 17.4 | BSD-3-Clause |
| xxhash | 4.0.2 | BSD-2-Clause |
| zstandard | 0.25.0 | BSD-3-Clause |

## npm runtime dependencies (direct)

| Package | Version | License |
|---|---|---|
| @ant-design/icons | 6.3.4 | MIT |
| @tanstack/react-query | 5.105.0 | MIT |
| @xyflow/react | 12.12.0 | MIT |
| antd | 6.6.8 | MIT |
| dayjs | 1.11.23 | MIT |
| react | 19.3.1 | MIT |
| react-dom | 19.3.1 | MIT |
| react-router-dom | 7.18.5 | MIT |

All 89 transitive npm runtime packages are MIT, except: d3-color, d3-dispatch, d3-drag, d3-interpolate,
d3-selection, d3-timer, d3-transition, d3-zoom (ISC) and d3-ease (BSD-3-Clause).

To regenerate: `uv export --no-dev` plus package metadata, and `npm ls --omit=dev --all --parseable`
with each package's `license` field.
