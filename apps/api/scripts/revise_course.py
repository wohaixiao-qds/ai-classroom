"""老课复审 CLI。

例子:
  uv run python scripts/revise_course.py init mcp-model-context-protocol --material ...
  uv run python scripts/revise_course.py review data/revisions/...
  uv run python scripts/revise_course.py promote data/revisions/... --map old=new
  uv run python scripts/revise_course.py promote data/revisions/... --relearn removed-checkpoint
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.legacy_revision import (
    create_revision,
    load_revision,
    promote_revision,
    review_revision,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="隔离复审并晋级一门历史课程")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("course_id")
    init.add_argument("--material", type=Path)
    init.add_argument("--revision-id")
    review = sub.add_parser("review")
    review.add_argument("revision", type=Path)
    review.add_argument("--material", type=Path)
    promote = sub.add_parser("promote")
    promote.add_argument("revision", type=Path)
    promote.add_argument("--map", action="append", default=[], metavar="OLD=NEW")
    promote.add_argument("--relearn", action="append", default=[], metavar="OLD",
                         help="被删除检查点对应的学习记录需重做，可重复指定")
    args = parser.parse_args()

    if args.command == "init":
        paths = create_revision(
            args.course_id,
            material_path=args.material,
            revision_id=args.revision_id,
        )
        print(paths.root)
        return
    paths = load_revision(args.revision)
    if args.command == "review":
        report = review_revision(paths, material_path=args.material)
        print(json.dumps(
            {"status": report.get("status"), "revision": str(paths.root)},
            ensure_ascii=False,
        ))
        return
    mapping: dict[str, str] = {}
    for pair in args.map:
        old, separator, new = pair.partition("=")
        if not separator or not old or not new:
            parser.error(f"--map 必须是 OLD=NEW: {pair}")
        if old in mapping:
            parser.error(f"旧检查点重复映射: {old}")
        mapping[old] = new
    print(json.dumps(promote_revision(
        paths,
        checkpoint_mapping=mapping or None,
        relearning_required=args.relearn or None,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
