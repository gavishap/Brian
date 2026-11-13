"""Write the API's OpenAPI schema to services/api/openapi.json (input for the mobile app's typed client).

Usage: uv run python scripts/export_openapi.py [--check]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from brian.main import create_app

TARGET = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> int:
    spec = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text() != spec:
            print("openapi.json is out of date: run `uv run python scripts/export_openapi.py`", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(spec)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
