"""CSL 课件校验 CLI：python scripts/validate_csl.py courses/xxx.csl.json

T1 验收工具：保证课件 JSON 符合 schema、script 句数与 fragments 对齐、
自学版含至少一个复述检查点。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas.csl import Course


def validate(path: Path) -> int:
    course = Course.model_validate_json(path.read_text(encoding="utf-8"))

    errors: list[str] = []
    for i, page in enumerate(course.pages, 1):
        # 每个动画必须挂在有效讲稿句之后
        n = len(page.script)
        for f in page.fragments:
            if not 0 <= f.after_sentence < n:
                errors.append(
                    f"第{i}页 {page.id}: fragment({f.effect},{f.target}) 挂在第 "
                    f"{f.after_sentence} 句,但讲稿只有 {n} 句"
                )
        if not page.script:
            errors.append(f"第{i}页 {page.id}: 讲稿为空")

    if course.scenario in ("自学", "复习"):
        has_cp = any(p.checkpoint for p in course.pages)
        if not has_cp:
            errors.append(f"场景为「{course.scenario}」但没有任何复述检查点")

    if errors:
        print(f"❌ {path.name}:")
        for e in errors:
            print(f"  - {e}")
        return 1

    cp = sum(1 for p in course.pages if p.checkpoint)
    sents = sum(len(p.script) for p in course.pages)
    print(f"✅ {path.name}: {len(course.pages)} 页 / {sents} 句讲稿 / {cp} 个检查点 / 场景={course.scenario}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: validate_csl.py <course.csl.json> [...]")
        sys.exit(2)
    sys.exit(max(validate(Path(p)) for p in sys.argv[1:]))
