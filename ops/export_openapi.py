"""Write the backend OpenAPI schema to web/openapi.json (input for `npm run gen:api`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from testagent.api.app import create_app  # noqa: E402
from testagent.core.secrets import SecretStore  # noqa: E402


class _NoDb:
    def ping(self) -> bool:
        return False


def main() -> int:
    app = create_app(_NoDb(), "unused", secrets=SecretStore(ROOT / "runtime" / "unused.json"))
    target = ROOT / "web" / "openapi.json"
    target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
