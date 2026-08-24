"""备课 Agent(P2·M2b)—— 备课材料(调研原料/笔记)→ CSL 课件,离线 CLI。

设计(docs/P2执行计划.md M2b,2026-08-24 对齐):
- 一课=一个子题:开场承接前置子题(位置感),不是「一个主题一课」
- 工具四件(铁律8 精选):init_course / write_page(按页追加落盘) / validate_csl / read_notes
- 终止客观化:模型自然收笔时,harness 再跑一次全文件校验——不过就打回继续,
  过了才算完(尺子说了算,不信模型嘴上说"好了")
- 来源确定性带入:init_course 后 harness 自动把材料来源写进 meta.sources(不靠模型自觉)
- MAX_TURNS=24 软着陆:耗尽交付当前版本+未完成清单(已写页都在盘上)
- trace 落 prep.jsonl(validate_failures=打回次数,循环健康度关键观测)

用法:
    uv run python -m app.agent.prep --material data/research/xx.material.json \
        [--prev "前置子题"]
    uv run python -m app.agent.prep \
        --note Agent/01-harness/03-Runtime/终止条件.md   # 复习路径
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.agent.tools import read_notes
from app.core.config import settings
from app.core.llm import get_llm_client
from app.core.trace import trace_prep
from app.schemas.csl import Page
from app.services.csl_validator import validate_course

MAX_TURNS = 24

PREP_PROMPT = """你是课件作者,把备课材料变成一份 CSL 课件(讲稿+动画+检查点)。

{position}

# 备课材料(每条要点带来源 id,讲稿里用到哪条就有据可查)
{material}

# 页型菜单(JSON 结构,kind 必须精确匹配)
- cover 封面:{{"kind":"cover","equation":"一句话核心公式(可空)",
  "meta":[["讲师","AI 老师"],["来源","调研/笔记"],["时长","约N分钟"]]}}
- formula 公式:{{"kind":"formula","items":["逐项弹出的元素"],"conclusion":"大字结论"}}
- duo 对比:{{"kind":"duo","left":{{"title":"…","tag":"小标签","body":"支持**加粗**"}},
  "right":{{…}}}}
- code 代码:{{"kind":"code","language":"python",
  "lines":[{{"code":"…","comment":"行尾注释"}}],"note":"结论"}}
- table 总结:{{"kind":"table","headers":["…"],"rows":[["…"]],"note":"结论"}}
- quiz 自测:{{"kind":"quiz","questions":["…"]}}

页骨架:{{"id":"p2-formula(英文slug)","eyebrow":"眉标","title":"页题","content":{{…}},
"script":[{{"text":"一句讲稿","audio":null}}],
"fragments":[{{"effect":"fade|pop|rise","target":null,"with_sentence":0}}],
"checkpoint":null 或 {{"question":"复述问题","hint":null,"pass_rule":"通过标准"}}}}

⚠ with_sentence 从 0 起算:第 1 句=0、第 2 句=1…;target 只能是字符串元素 id 或 null。
write_page 重交同 id 的页 = 替换那页(改错就重交同 id,不要换 id 重写)。

# 讲到什么,亮什么(质量底线)
每写一句讲稿自问:这句话提到的元素,画面上有吗?fragment.with_sentence 挂到
提到它的那句;formula 逐项弹、code 逐行浮、table 逐行进——零 fragment 的动画页过不了校验。

# 讲稿风格(给 TTS 念的)
口语短句,每句 1~2 个逗号句;类比优先;宁少勿多。共 5~9 页,总时长 8~15 分钟。

# 检查点(场景为自学/复习时)
每个讲完的大子题,那页 checkpoint 填复述问题+pass_rule(通过标准写具体)。

# 流程
1. 先在心里排页面规划(几页、每页讲什么)
2. init_course(id=子题英文slug, title=子题名, scenario="自学", source_notes=["材料路径"])
3. write_page 逐页追加(一次一页,别贪)
4. 每写 2~3 页 validate_csl 自查一次,有错即改
5. 全部写完终验通过后,收笔说一句交付总结(不再调工具)"""


# ---------- 工具实现(闭包持有课件路径与材料来源) ----------


def _course_path(course_id: str) -> Path:
    return settings.courses_dir / f"{course_id}.csl.json"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return d if isinstance(d, dict) else None


def _make_tools(
    material_sources: list[dict[str, Any]],
    material_path: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    state: dict[str, Any] = {"course_id": None}

    def init_course(id: str, title: str, scenario: str, source_notes: list[str]) -> str:  # noqa: A002
        p = _course_path(id)
        if p.exists():
            return f"(课件 {id} 已存在,换个 id 或先删旧文件)"
        # source_notes 语义=材料路径(vault 相对路径或原料文件),溯源/课表关联靠它。
        # 确定性覆盖:模型爱填小节标题之类的噪音,一律不认(实测踩过)
        if material_path:
            source_notes = [material_path]
        course = {
            "id": id,
            "title": title,
            "scenario": scenario,
            "meta": {
                "source_notes": source_notes,
                # 来源确定性带入:材料里的调研来源 harness 直接写进 meta.sources(有据链路终点)
                "sources": [
                    {"title": str(s.get("title", ""))[:80], "url": str(s.get("url", ""))}
                    for s in material_sources
                ],
                "duration_min": None,
                "version": 1,
            },
            "pages": [],
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
        state["course_id"] = id
        return f"课件骨架已建:{p.name}。现在 write_page 逐页追加。"

    def write_page(page: dict[str, Any]) -> str:
        cid = state["course_id"]
        if not cid:
            return "(还没 init_course,先建课件骨架)"
        try:
            Page.model_validate(page)  # 单页即时校验:错了当场反馈,别等终验
        except Exception as e:  # noqa: BLE001 校验反馈本身就是观测
            return f"(这页结构不对,改完重交:{e})"[:600]
        p = _course_path(cid)
        course = _load(p)
        if course is None:
            return "(课件文件读不回,重新 init_course)"
        # upsert-by-id:同 id = 替换该页(改错的原语),否则追加。
        # 没有替换语义,模型改错只能整页重交 → 追加出重复页,循环空转(实测踩过)。
        pid = page.get("id")
        idx = next((i for i, pg in enumerate(course["pages"]) if pg.get("id") == pid), None)
        if idx is None:
            course["pages"].append(page)
            msg = f"已写入第{len(course['pages'])}页({pid}),共需 5~9 页。"
        else:
            course["pages"][idx] = page
            msg = f"已替换第{idx + 1}页({pid})。"
        p.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
        return msg

    def validate_csl() -> str:
        cid = state["course_id"]
        if not cid:
            return "(还没 init_course)"
        course = _load(_course_path(cid))
        if course is None:
            return "(课件文件读不回)"
        r = validate_course(course)
        head = ("✅ " if r["ok"] else "❌ ") + str(r["summary"])
        body = "".join(f"\n  ✗ {e}" for e in r["errors"])
        warns = r["warnings"]
        # 音频缺失是生成期正常态,warn 又多又吵——只放前 5 条,免得淹没 error
        if len(warns) > 5:
            n_more = len(warns) - 5
            warns = warns[:5] + [f"(其余 {n_more} 条 warning 多为「无音频路径」,TTS 前正常)"]
        body += "".join(f"\n  ⚠ {w}" for w in warns)
        return str(head + body)

    tools = [
        {
            "name": "init_course",
            "description": "建课件骨架(先于 write_page)。id 用子题英文短横线 slug。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "scenario": {"type": "string", "enum": ["自学", "复习", "对外"]},
                    "source_notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "scenario", "source_notes"],
            },
        },
        {
            "name": "write_page",
            "description": "追加一页(完整页 JSON,结构照页型菜单)。一次一页;"
            "重交同 id = 替换该页(改错用)。",
            "input_schema": {
                "type": "object",
                "properties": {"page": {"type": "object"}},
                "required": ["page"],
            },
        },
        {
            "name": "validate_csl",
            "description": "校验当前课件,返回逐条可改的反馈。每写 2~3 页自查一次。",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "read_notes",
            "description": "查学员已有笔记补充衔接(只读)。",
            "input_schema": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
            },
        },
    ]
    dispatch = {
        "init_course": lambda a: init_course(**a),
        "write_page": lambda a: write_page(a.get("page", {})),
        "validate_csl": lambda _a: validate_csl(),
        "read_notes": lambda a: read_notes(a["keyword"]),
    }
    return tools, dispatch, state


# ---------- 材料 ----------


def _load_material(material_path: str) -> dict[str, Any]:
    d = json.loads(Path(material_path).read_text(encoding="utf-8"))
    if not isinstance(d, dict) or "groups" not in d:
        msg = f"材料格式不对(应是找资料 agent 产出的原料 JSON): {material_path}"
        raise ValueError(msg)
    return d


def _material_from_note(note_rel: str) -> dict[str, Any]:
    """复习路径:vault 笔记 → 材料形态(无来源,source_notes 由模型填笔记路径)。"""
    p = settings.kb_dir / note_rel
    text = p.read_text(encoding="utf-8")
    groups: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for ln in text.splitlines():
        if ln.startswith("## "):
            cur = {"heading": ln[3:].strip(), "points": []}
            groups.append(cur)
        elif ln.strip().startswith(("-", "*")) and cur is not None:
            cur["points"].append({"text": ln.strip().lstrip("-* ").strip()})
    if not groups:
        groups = [{"heading": p.stem, "points": [{"text": text[:2000]}]}]
    return {
        "topic": p.stem,
        "subtopic": p.stem,
        "sources": [],
        "groups": groups,
        "_from_note": note_rel,
    }


def _render_material(m: dict[str, Any]) -> str:
    srcs = m.get("sources") or []
    head = f"主题:{m.get('topic')} / 本次子题:{m.get('subtopic')}\n来源清单:"
    for s in srcs:
        head += f"\n  [{s.get('id')}] {s.get('title','')[:50]} | {s.get('url','')}"
    if not srcs:
        head += "\n  (来自学员笔记,无网页来源)"
    body = ""
    for g in m.get("groups", []):
        body += f"\n## {g.get('heading')}"
        for pt in g.get("points", []):
            sid = f"(源[{pt.get('source_id')}])" if pt.get("source_id") else ""
            body += f"\n- {pt.get('text')}{sid}"
    return head + body


# ---------- 主循环 ----------


def run_prep(material: dict[str, Any], prev_subtopic: str | None = None) -> dict[str, Any]:
    tools, dispatch, state = _make_tools(
        material.get("sources") or [],
        material_path=material.get("_material_path"),
    )
    position = (
        f"本课在「{material.get('topic')}」学习框架中的位置:前一课讲了「{prev_subtopic}」,"
        f"开场用一句话承接它。" if prev_subtopic else "这是该主题的第一课。"
    )
    prompt = PREP_PROMPT.format(position=position, material=_render_material(material))
    client = get_llm_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    tool_calls: list[dict[str, Any]] = []
    validate_failures = 0
    text_out = ""
    t0 = time.perf_counter()

    def final_check() -> list[str] | None:
        """天然收笔后的强校验:不过打回(None=通过)。终止客观化的关键一步。"""
        if state["course_id"] is None:
            return ["还没 init_course——先建课件骨架"]
        course = _load(_course_path(state["course_id"]))
        if course is None:
            return ["课件文件读不回"]
        r = validate_course(course)
        return None if r["ok"] else r["errors"]

    for turn in range(MAX_TURNS):
        last_turn = turn == MAX_TURNS - 1
        resp = client.messages.create(
            model=settings.llm_model,
            max_tokens=8192,
            messages=messages,  # type: ignore[arg-type]  # dict 字面量 vs SDK TypedDict,同 tutor.py
            tools=[] if last_turn else tools,  # type: ignore[arg-type]
        )
        u = resp.usage
        usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        text_out = "".join(b.text for b in resp.content if b.type == "text")

        if resp.stop_reason != "tool_use":
            errs = final_check()
            if errs is None:
                course = _load(_course_path(state["course_id"])) if state["course_id"] else None
                if course is not None:
                    trace_prep(
                        course_id=str(course["id"]),
                        subtopic=str(material.get("subtopic")),
                        pages=len(course["pages"]),
                        validate_failures=validate_failures,
                        ok=True,
                        elapsed_s=time.perf_counter() - t0,
                        tool_calls=tool_calls,
                        usage=usage,
                    )
                    return {"ok": True, "course": course, "report": text_out, "usage": usage}
                errs = ["课件文件读不回"]  # 校验过了文件却没了,罕见,打回重建
            validate_failures += 1
            messages.append({"role": "assistant", "content": "…"})
            messages.append(
                {
                    "role": "user",
                    "content": "收笔前终验没过,逐条修完再收:\n- " + "\n- ".join(errs[:10]),
                }
            )
            continue

        messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            ts = time.time()
            try:
                out, err = dispatch[b.name](dict(b.input)), None
            except Exception as e:  # noqa: BLE001 工具炸了不拖垮循环(错误回收)
                out, err = f"(工具执行出错: {e})", str(e)
            tool_calls.append(
                {
                    "name": b.name,
                    "ms": round((time.time() - ts) * 1000),
                    "error": err,
                    "feedback": str(out)[:300],  # 观测:工具回了什么(打回原因就在这)
                }
            )
            print(f"  [{b.name}] {str(out)[:200]}")  # CLI 实时可见,复盘不用翻盘上文件
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
        messages.append({"role": "user", "content": results})

    # 软着陆:交付当前版本(已写页都在盘上)
    cid = state["course_id"]
    course = _load(_course_path(cid)) if cid else None
    trace_prep(
        course_id=cid or "",
        subtopic=str(material.get("subtopic")),
        pages=len(course["pages"]) if course else 0,
        validate_failures=validate_failures,
        ok=False,
        elapsed_s=time.perf_counter() - t0,
        tool_calls=tool_calls,
        usage=usage,
        error="MAX_TURNS 耗尽(软着陆,已写页都在盘上)",
    )
    return {"ok": False, "course": course, "report": text_out, "usage": usage}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="备课 Agent:材料/笔记 → CSL 课件")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--material", help="找资料产出的原料 JSON 路径(新课)")
    g.add_argument("--note", help="vault 笔记相对路径(复习)")
    ap.add_argument("--prev", help="前置子题名(位置感,开场承接)")
    ap.add_argument("--no-tts", action="store_true", help="跳过音频编译(调试用)")
    a = ap.parse_args()

    m = _load_material(a.material) if a.material else _material_from_note(a.note)
    m["_material_path"] = a.material or a.note  # vault 相对路径,课表关联靠它
    r = run_prep(m, prev_subtopic=a.prev)
    if r["ok"]:
        from app.services.tts_compile import compile_course_audio, publish_courses

        c = r["course"]
        print(f"\n✅ 课件已交付:courses/{c['id']}.csl.json")
        print(f"   {len(c['pages'])} 页 · {sum(len(p['script']) for p in c['pages'])} 句")
        print(f"   检查点 {sum(1 for p in c['pages'] if p.get('checkpoint'))} 个")
        srcs = c.get("meta", {}).get("sources", [])
        if srcs:
            print(f"   来源 {len(srcs)} 个(有据可查)")
        if not a.no_tts:
            print("\n生成音频(edge-tts,句间限速,稍候)…")
            done, fail = compile_course_audio(str(c["id"]))
            print(f"音频: 新生成 {done}, 失败 {fail}")
        publish_courses()
        print("前端已就绪,打开课表即可上课")
    else:
        print("\n⚠️ 软着陆:MAX_TURNS 耗尽,当前版本已落盘,人工接着审")
