"""v1(页/句)→v2(节/块) 一次性迁移(P6·M1)。映射规则见 docs/P6执行计划.md 第三节。

用法:
    uv run python scripts/migrate_csl_v2.py            # 试运行:产物写 data/v2_staging/,原件不动
    uv run python scripts/migrate_csl_v2.py --apply    # 原地覆盖(原件先备份到 data/v1_backup/)

映射要点:
- 节 id 沿用旧页 id → 批改/复习历史(checkpoint_mastery 的 page_id)零映射成本
- 讲稿按 ≤4 句合一段落(机械合并;口语→书面损耗已知,人工润色后补)
- 页型→块:cover→表格+提示框 / formula→段落+提示框 / duo→对比表格 /
  code/table→同名块 / quiz 页→quiz 块(自测题) / checkpoint→节末 quiz 块
- fragments/audio 丢弃(reveal 专属;v2 音频留位为 null)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.services.csl_validator import validate_course  # noqa: E402


def _join_script(script: list[dict[str, Any]]) -> list[str]:
    """讲稿句 → 每 ≤4 句一个段落文本(直接拼接,中文口语无需分隔符)。"""
    texts = [str(s.get("text", "")).strip() for s in script]
    texts = [t for t in texts if t]
    return ["".join(texts[i : i + 4]) for i in range(0, len(texts), 4)]


def _content_blocks(
    content: dict[str, Any], page_id: str, warnings: list[str]
) -> list[dict[str, Any]]:
    """页型内容 → 块列表(机械映射,保信息不保版式)。"""
    kind = content.get("kind")
    out: list[dict[str, Any]] = []

    if kind == "cover":
        if content.get("equation"):
            out.append({"type": "callout", "kind": "note", "text": f"核心式:{content['equation']}"})
        rows = [[str(k), str(v)] for k, v in content.get("meta", [])]
        if rows:
            out.append({"type": "table", "header": ["项目", "内容"], "rows": rows})

    elif kind == "formula":
        items = [str(x) for x in content.get("items", [])]
        if items:
            out.append({"type": "p", "text": f"公式要素:`{' '.join(items)}`"})
        if content.get("conclusion"):
            out.append({"type": "callout", "kind": "tip", "text": str(content["conclusion"])})

    elif kind == "diagram":
        # v1 的 SVG 资产页型(P2 已弃用方向):无机械等价,落占位待人工处理
        warnings.append(
            f"{page_id}: v1 diagram(SVG 资产 {content.get('asset')})→ 占位块,需人工补 mermaid"
        )
        asset = str(content.get("asset", "?"))
        out.append({
            "type": "diagram", "lang": "mermaid",
            "code": f'graph TD\n  TODO["待人工改写:原 SVG 资产 {asset}"]',
        })

    elif kind == "duo":
        left, right = content.get("left", {}), content.get("right", {})
        tag = " / ".join(t for t in (left.get("tag"), right.get("tag")) if t)
        out.append({
            "type": "table",
            "header": [str(left.get("title", "左")), str(right.get("title", "右"))],
            "rows": [[str(left.get("body", "")), str(right.get("body", ""))]],
            "caption": tag or None,
        })

    elif kind == "code":
        lines = [
            str(ln.get("code", "")) + (f"  # {ln['comment']}" if ln.get("comment") else "")
            for ln in content.get("lines", [])
        ]
        out.append({
            "type": "code", "language": str(content.get("language", "text")),
            "code": "\n".join(lines), "caption": content.get("note"),
        })

    elif kind == "table":
        out.append({
            "type": "table", "header": list(content.get("headers", [])),
            "rows": [list(map(str, r)) for r in content.get("rows", [])],
            "caption": content.get("note"),
        })

    elif kind == "quiz":
        for j, q in enumerate(content.get("questions", []), 1):
            out.append({"type": "quiz", "id": f"{page_id}-q{j}", "question": str(q)})

    else:
        warnings.append(f"{page_id}: 未知页型「{kind}」→ 仅保留讲稿段落")

    return out


def page_to_section(page: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """一页 → 一节。节 id 沿用旧页 id。"""
    blocks: list[dict[str, Any]] = [
        {"type": "p", "text": t} for t in _join_script(page.get("script", []))
    ]
    blocks.extend(_content_blocks(page.get("content", {}) or {}, str(page.get("id")), warnings))

    cp = page.get("checkpoint")
    if cp:
        blocks.append({
            "type": "quiz", "id": f"{page['id']}-cp",
            "question": str(cp.get("question", "")),
            "hint": cp.get("hint"),
            "pass_rule": cp.get("pass_rule"),
        })

    heading = page.get("title") or page.get("eyebrow") or str(page.get("id"))
    if not blocks:  # 兜底:空页不至于零块
        blocks = [{"type": "p", "text": heading}]
    return {"id": str(page["id"]), "heading": str(heading), "blocks": blocks, "audio": None}


def migrate_course(d: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    meta = dict(d.get("meta", {}))
    meta.pop("version", None)  # 顶层 version=2 是唯一格式标记,不留两处真相
    v2 = {
        "id": d["id"],
        "title": d["title"],
        "scenario": d["scenario"],
        "version": 2,
        "meta": meta,
        "sections": [page_to_section(p, warnings) for p in d.get("pages", [])],
    }
    return v2, warnings


def main() -> None:
    ap = argparse.ArgumentParser(description="CSL v1→v2 一次性迁移")
    ap.add_argument("--apply", action="store_true", help="原地覆盖(默认只写 data/v2_staging/)")
    a = ap.parse_args()

    src_dir = settings.courses_dir
    out_dir = src_dir if a.apply else settings.data_dir / "v2_staging"
    backup_dir = settings.data_dir / "v1_backup"
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(src_dir.glob("*.csl.json"))
    if not files:
        raise SystemExit(f"没有找到课件:{src_dir}")

    n_ok = 0
    for p in files:
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("version") == 2:
            print(f"↩ 跳过(已是 v2):{p.name}")
            continue
        v2, warnings = migrate_course(d)
        for w in warnings:
            print(f"  ⚠ {w}")
        r = validate_course(v2)
        target = out_dir / p.name
        if not r["ok"]:
            print(f"  ❌ {p.name} 迁移后校验不过,未写出:{r['errors'][:3]}")
            continue
        if a.apply:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, backup_dir / p.name)
        target.write_text(json.dumps(v2, ensure_ascii=False, indent=2), encoding="utf-8")
        n_ok += 1
        print(f"  ✅ {p.name} → {target}({r['summary']})")

    if a.apply:
        mode = f"已原地覆盖(备份在 {backup_dir})"
    else:
        mode = "试运行产物在 data/v2_staging/(未动原件)"
    print(f"\n完成:{n_ok}/{len(files)} 门迁移,{mode}")


if __name__ == "__main__":
    main()
