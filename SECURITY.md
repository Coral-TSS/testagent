# Security policy

## Supported versions

TestAgent is in its initial release (v0.1.x). Security fixes are made on the latest release only.

## Scope and threat model

TestAgent v0.1 is designed for **a single user on a local machine or a trusted network**:

- there are no user accounts; access is protected by a bearer access token and a host check
  (`localhost` by default, extend with `TESTAGENT_ALLOWED_HOSTS`);
- the agent runs generated test code (pytest/Playwright) on the platform host or container against the
  environments you configure;
- the model API key is stored locally in `runtime/secrets.json` (file mode 600, DPAPI on Windows).

Do **not** expose the platform to the internet, and only point it at systems you are allowed to test.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/Coral-TSS/testagent/security/advisories/new) for this repository, or contact the
maintainers privately. Include the version, steps to reproduce and the impact. We aim to acknowledge
reports within a week.
