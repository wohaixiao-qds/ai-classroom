"""CSL 课件校验 CLI:uv run python scripts/validate_csl.py courses/xxx.csl.json

薄壳:逻辑全在 app/services/csl_validator.py(备课 agent 循环同源调用)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.csl_validator import validate_course_json


def validate(path: Path) -> int:
    r = validate_course_json(path.read_text(encoding="utf-8"))
    if not r["ok"]:
        print(f"❌ {path.name}:")
        for e in r["errors"]:
            print(f"  ✗ {e}")
    else:
        print(f"✅ {path.name}: {r['summary']}")
    for w in r["warnings"]:
        print(f"  ⚠ {w}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: validate_csl.py <course.csl.json> [...]")
        sys.exit(2)
    code = 0
    for p in sys.argv[1:]:
        try:
            code = max(code, validate(Path(p)))
        except (OSError, json.JSONDecodeError) as e:
            print(f"❌ {p}: {e}")
            code = 1
    sys.exit(code)
