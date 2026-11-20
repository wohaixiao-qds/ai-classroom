"""只读盘点存量课件的当前门禁与老课复审状态。

退出码:
  0  所有课件均已晋级且当前发布门禁通过
  2  存在未审、候选、仅审查未晋级或门禁阻断的课件
  1  输入/运行错误
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.legacy_revision import audit_legacy_courses


def main() -> int:
    parser = argparse.ArgumentParser(description="只读审计所有存量课件")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()
    try:
        report = audit_legacy_courses()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"审计失败:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    summary = report["summary"]
    return 0 if (
        summary["total"] == summary["promoted"]
        and summary["publication_allowed"] == summary["total"]
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
