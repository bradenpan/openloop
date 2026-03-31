"""Export the FastAPI app's OpenAPI schema to contract/openapi.json.

Usage:
    python scripts/export_openapi.py

The generated JSON file is consumed by `openapi-typescript` to produce
TypeScript types for the frontend.
"""

import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from backend.openloop.main import app  # noqa: E402


def main() -> None:
    schema = app.openapi()
    out_path = project_root / "contract" / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(f"OpenAPI schema written to {out_path}")


if __name__ == "__main__":
    main()
