"""将静态 CSL 的 Pydantic schema 包装为 OpenAPI,复用现有 TS 生成器。无需起 API。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import TypeAdapter

from app.schemas.csl import AnyCourse


def csl_openapi() -> dict[str, Any]:
    schema = TypeAdapter(AnyCourse).json_schema(ref_template="#/components/schemas/{model}")
    definitions = schema.pop("$defs")
    definitions["AnyCourse"] = schema
    return {"openapi": "3.1.0", "info": {"title": "Static CSL contract", "version": "2"},
            "paths": {}, "components": {"schemas": definitions}}


if __name__ == "__main__":
    print(json.dumps(csl_openapi(), ensure_ascii=False))
