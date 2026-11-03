# Security policy

## Supported versions

Security fixes are made on the latest release only.

## Scope and threat model

TestAgent is designed for **a small, trusted team**:

- every request needs a signed-in account (roles `admin` and `member`); passwords are hashed with
  argon2id; sessions are server-side, in an HttpOnly cookie (`Secure` over HTTPS, `SameSite=Lax`), with
  a CSRF token for writes; sign-in attempts are rate-limited per address and an account is locked for
  15 minutes after 5 wrong passwords;
- requests are only accepted for `localhost`, `TESTAGENT_PUBLIC_HOST` and `TESTAGENT_ALLOWED_HOSTS`;
- on a server, only the Caddy proxy is published (HTTPS on 443); the platform and the demo SUT stay
  bound to `127.0.0.1`;
- **every signed-in user can effectively run code in the platform container**: the agent writes and runs
  pytest/Playwright scripts there and the platform connects to any environment URL you configure.
  Roles prevent mistakes (only admins change the model settings and SUT start commands, and manage
  accounts); they are not an isolation boundary. Only give accounts to people you trust;
- the model API key is stored locally in `runtime/secrets.json` (file mode 600, DPAPI on Windows).

Only point the platform at systems you are allowed to test.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/Coral-TSS/testagent/security/advisories/new) for this repository, or contact the
maintainers privately. Include the version, steps to reproduce and the impact. We aim to acknowledge
reports within a week.
