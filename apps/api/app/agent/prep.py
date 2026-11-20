"""备课 Agent(P6·M3)—— 备课材料(调研原料/笔记)→ v2 书页课件(节→块),离线 CLI。

设计(docs/P6执行计划.md M3,2026-11-02 对齐):
- 一课=一个子题:开场承接前置子题(位置感),不是「一个主题一课」
- 规划外显:submit_plan 先行,harness 校验(节覆盖材料组/quiz≥3 硬闸/3~9 节),
  交互模式人审(回车照单/文字意见喂回重排一次);两次不过→静态模板兜底,永不空转
- 工具五件(铁律8 精选):submit_plan / init_course / write_section(upsert-by-id)
  / validate_csl / read_notes
- 终止客观化:模型自然收笔时,harness 再跑一次全文件校验——不过就打回继续,
  过了才算完(尺子说了算,不信模型嘴上说"好了")
- 来源确定性带入:init_course 后 harness 自动把材料来源写进 meta.sources(不靠模型自觉)
- MAX_TURNS=24 软着陆:耗尽交付当前版本(已写节都在盘上)
- trace 落 prep.jsonl(validate_failures=打回次数,循环健康度关键观测)

用法:
    uv run python -m app.agent.prep --material data/research/xx.material.json \
        [--prev "前置子题"]
    uv run python -m app.agent.prep \
        --note Agent/01-harness/03-Runtime/终止条件.md   # 复习路径
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.agent.tools import emit_call, read_notes
from app.core.config import settings
from app.core.llm import get_llm_client
from app.core.prompts import DEV_LANDING_RULE, OFF_THE_SHELF_RULE, PITFALL_RULE
from app.core.trace import observed, run_context, trace_prep, update_run
from app.schemas.csl import Section
from app.services.csl_validator import validate_course
from app.services.evidence import course_evidence_report, material_evidence

MAX_TURNS = 24

PREP_PROMPT = """你是教材作者,把备课材料写成一份 v2 书页课件(滚动文章:节→块,给「读」不给「念」)。

{position}

# 备课材料(每条带证据 ID,缺原文的材料明确待审)
{material}

# 学员已有课程(判断先修关系用;学习路线的学习顺序就靠它生长)
{existing}

init_course 时填 depends_on:本课内容**预设**了哪门已有课的概念,就填它,
格式 [{{"id":"已有课id","reason":"为什么先学它(一句话)"}}]。
- id 只能取上面清单里的,不许编造;至多 2 门(先修链宁短勿长)
- 独立入门课/什么都不预设 → 填 []。判断标准:删掉那门课的知识,本课还讲不讲得通?

# 第一步:submit_plan(规划先行,人审通过才能动笔)
sections: [{{"id":"s1-xxx(英文slug)","heading":"节标题",
"has_quiz":true,"covers":"材料组名(可逗号分隔多个)"}}]
- 3~9 节,每节一个论点群;带复述检查点(has_quiz)的节 ≥3(材料组不足 3 组时每组都带)
- covers 保证材料每组都被至少一节覆盖,别漏组
- 规划会给人审;被给修改意见就按意见重排再交

{shared_style}

# 流程
1. submit_plan(规划 → 人审)
2. init_course(id=子题英文slug, title=子题名, scenario="自学",
   source_notes=["材料路径"], depends_on=[先修课,见上节])
3. write_section 逐节追加(一次一节,照计划写;重交同 id = 替换该节,改错别换 id)
4. 每写 2~3 节 validate_csl 自查一次,有错即改
5. 全部写完终验通过后,收笔说一句交付总结(不再调工具)"""


# 共享段:块型纪律与文风红线(全量/续写两套 prompt 共用,防止漂移)。值为 format 后形态(单花括号)。
_SHARED_STYLE = """# 块型菜单(blocks 数组,type 必须精确匹配)
- p 段落(主力):{"type":"p","text":"书面 prose 一段,3~6 句,支持**加粗**与 `行内代码`"}
- diagram 示意图(每课 1~3 张,只画流程/结构/关系):
  {"type":"diagram","lang":"mermaid","code":"graph TD\\n  A[输入] --> B[输出]","caption":"图题"}
  ⚠ 只写保守的 graph TD / graph LR;节点文本别带括号引号等特殊字符——语法错前端会降级成代码块
- code:{"type":"code","language":"python","code":"真实可读的示例","caption":"说明"}
- table:{"type":"table","header":["…"],"rows":[["…"]],"caption":"表题"}
- callout:{"type":"callout","kind":"tip|warn|note","text":"关键结论或容易踩的坑"}
- quiz 复述检查点(has_quiz 的节末必放):
  {"type":"quiz","id":"<节id>-cp","question":"复述问题","hint":null,"pass_rule":"具体可判的通过标准"}
- flashcards(选配,每节 0~2 张):{"type":"flashcards","cards":[{"front":"问","back":"答"}]}

# 文风(书面 prose)
一段只讲一个论点;术语首现给一句白话解释;类比保留但别滥用。
禁课堂腔(「接下来我们」「好了,以上就是」「让我们」);不写「本课将介绍」,
第一节直接进主题。每节 2~4 个 p 块,宁短勿凑。

# 检查点纪律(教学闸)
quiz 的 question 问「关系/区别/步骤/为什么」这类要动脑复述的,别问填空「是什么」;
pass_rule 写具体判定标准(例:「答出四层名称和顺序」),批改 agent 靠它判;
id 固定用「<节id>-cp」。

# 原文证据
材料每条标有证据[g1p1]等 ID。承载该要点的块填 "evidence_ids":["g1p1"];
只用材料中实际存在的 ID,关键数字/版本/规范断言必须关联对应证据。
原文摘录保持原语言,正文可解释改写;不扩大原文的适用条件。
成绩数字不等于受控对照,不得无依据归因为全部提升来自某组件;组合系统不等于贡献各占一半。
个别团队案例不得概括所有团队;评分方式按目标选择,不得排成固定可靠性顺序。
标为 unsupported 的要点不要作为事实使用;partial/uncertain/unreviewed 如实保留限制。
练习、自造示例、类比可留空 evidence_ids,但明确标为示例,不能冒充来源事实。
引用只建立追溯关系,不能声称正文已被事实核验。

""" + PITFALL_RULE + "\n\n" + DEV_LANDING_RULE + "\n\n" + OFF_THE_SHELF_RULE + "\n"


# ---------- 工具实现(闭包持有课件路径与材料来源) ----------


def _course_path(course_id: str) -> Path:
    return settings.courses_dir / f"{course_id}.csl.json"


def _op_log(course_id: str, op: str, message: str) -> None:
    """课件操作日志(P5·T4,#27):append-only 一行一操作,人审可见「课件经历了什么」。"""
    if not course_id:
        return
    p = settings.data_dir / "research" / f"{course_id}.log.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(f"# {course_id} 课件操作日志\n", encoding="utf-8")
    ts = time.strftime("%H:%M:%S")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"- `{ts}` **{op}** — {message[:160]}\n")


def _load(path: Path) -> dict[str, Any] | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return d if isinstance(d, dict) else None


def _course_ids() -> set[str]:
    """现有课程 id 集(先修引用的合法域)。"""
    return {p.name[: -len(".csl.json")] for p in settings.courses_dir.glob("*.csl.json")}


def _course_brief() -> str:
    """现有课程速览(注入备课 prompt,判断先修关系用)。一行一门:id | 标题 | 大纲。

    v2 读节 heading、v1 读页标题(迁移期双版本);每门截 9 条、每条 20 字。
    """
    lines: list[str] = []
    for p in sorted(settings.courses_dir.glob("*.csl.json")):
        d = _load(p)
        if d is None:
            continue
        units = d.get("sections") or d.get("pages") or []
        outline = "/".join(
            str(
                u.get("heading")
                or u.get("title")
                or u.get("eyebrow")
                or u.get("id", "")
            )[:20]
            for u in units[:9]
        )
        lines.append(f"- {d.get('id')} | {d.get('title', '')} | 大纲:{outline}")
        if len(lines) >= 40:
            lines.append("- (其余课程略——先修 id 只可能取自上面列出的)")
            break
    if not lines:
        return "(学员还没有任何课程,本课是第一门,depends_on 填空数组 [])"
    return "\n".join(lines)


def _covers_key(s: str) -> str:
    """covers/组名匹配键:去空白取前 8 字,容忍模型改写组名时的微小漂移。"""
    return "".join(str(s).split())[:8]


def _plan_path(course_id: str) -> Path:
    return settings.data_dir / "research" / f"{course_id}.plan.json"


def _save_plan(course_id: str, plan: list[dict[str, Any]], groups: list[str],
               binding: dict[str, Any] | None = None, learning_goal: str = "") -> None:
    """规划独立于发布课件,原子替换避免中断留下半份 JSON。"""
    path = _plan_path(course_id)
    if binding:
        from app.core.job_store import ensure_active

        ensure_active(binding)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "course_id": course_id, "sections": plan, "groups": groups,
               "learning_goal": learning_goal}
    if binding:
        payload.update(job_binding_id=binding["id"], material_hash=binding["material_hash"])
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False) as file:
        temp = Path(file.name)
        try:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    if binding:
        from app.core.job_store import record_plan

        record_plan(str(binding["id"]), path)


def _valid_goal_check(check: Any) -> bool:
    return isinstance(check, dict) and all(
        isinstance(check.get(key), str) and check[key].strip()
        for key in ("question", "pass_rule")
    )


def _plan_delivery_errors(course: dict[str, Any], plan: list[dict[str, Any]] | None,
                          learning_goal: str = "") -> list[str]:
    """只验可确定的规划兑现;covers 是写作约定,不冒充语义覆盖证明。"""
    if not plan:
        return ["还没有通过的课程规划——先 submit_plan"]
    sections = course.get("sections", [])
    ids = [s.get("id") for s in sections]
    planned_ids = [s["id"] for s in plan]
    errors = []
    if len(ids) != len(set(ids)):
        errors.append("实际课件存在重复节 id,按规划保留唯一一节")
    for item in plan:
        sid = item["id"]
        section = next((s for s in sections if s.get("id") == sid), None)
        if section is None:
            errors.append(f"规划节 {sid}「{item['heading']}」尚未交付,用 write_section 补齐")
        elif item["has_quiz"] and not any(
            b.get("type") == "quiz" and str(b.get("pass_rule") or "").strip()
            for b in section.get("blocks", [])
        ):
            errors.append(f"规划节 {sid} 缺少带明确 pass_rule 的测验,重交同 id 修正")
        check = item.get("goal_check")
        if isinstance(check, dict) and _valid_goal_check(check) and section is not None and not any(
            b.get("type") == "quiz" and b.get("question") == check["question"]
            and b.get("pass_rule") == check["pass_rule"] for b in section.get("blocks", [])
        ):
            errors.append(f"规划节 {sid} 未交付约定的目标应用题与判分标准")
    if learning_goal and not any(_valid_goal_check(item.get("goal_check")) for item in plan):
        errors.append("规划缺大纲目标应用题,不能只交概念复述;需补交目标验收规划")
    extra = [sid for sid in ids if sid not in planned_ids]
    if extra:
        errors.append(f"课件含规划外节 {extra},需按原规划修正")
    if not extra and len(ids) == len(planned_ids) and ids != planned_ids:
        errors.append("实际节顺序与规划不符,按原规划逐节重交修正")
    return errors


def _template_plan(groups: list[str], subtopic: str) -> list[dict[str, Any]]:
    """静态默认规划(两次规划未过时兜底,DeepTutor #25「永不空转」):
    首节 intro + 每材料组一节;末 3 组带检查点(不足 3 组则全带)。"""
    quiz_groups = set(groups[-3:]) if len(groups) >= 3 else set(groups)
    secs: list[dict[str, Any]] = [
        {"id": "s0-intro", "heading": f"{subtopic}:这门课讲什么", "has_quiz": False, "covers": ""}
    ]
    for i, g in enumerate(groups, 1):
        secs.append(
            {"id": f"s{i}", "heading": g[:30], "has_quiz": g in quiz_groups, "covers": g}
        )
    return secs


def _make_tools(
    material_sources: list[dict[str, Any]],
    material_path: str | None = None,
    material_topic: str | None = None,
    material_groups: list[str] | None = None,
    job_binding: dict[str, Any] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
    learning_goal: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    groups = material_groups or []
    state: dict[str, Any] = {"course_id": None, "plan": None, "plan_reviews": 0}

    def submit_plan(sections: list[dict[str, Any]]) -> str:
        """规划外显(P5·T2 并入):harness 确定性校验 → 人审 → 兜底。"""
        if state["course_id"] and state["plan"] is not None:
            return "(已建课件的规划已锁定,按原规划补齐或重交同 id 修错)"
        state["plan_reviews"] += 1
        problems: list[str] = []
        n = len(sections)
        if not 3 <= n <= 9:
            problems.append(f"规划了 {n} 节,合法范围 3~9")
        ids = [s.get("id") for s in sections if isinstance(s, dict)]
        if len(ids) != n or any(not isinstance(sid, str) or not sid.strip() for sid in ids):
            problems.append("每个规划节必须有非空字符串 id")
        elif len(ids) != len(set(ids)):
            problems.append("规划节 id 重复,每节必须唯一")
        if any(not isinstance(s, dict) or not str(s.get("heading") or "").strip()
               for s in sections):
            problems.append("规划节标题不能为空")
        if state["course_id"]:
            existing_course = _load(_course_path(state["course_id"])) or {}
            missing_ids = [s["id"] for s in existing_course.get("sections", [])
                           if s["id"] not in ids]
            if missing_ids:
                problems.append(f"恢复规划必须保留已有节 id:{missing_ids}")
        n_quiz = sum(1 for s in sections if isinstance(s, dict) and s.get("has_quiz"))
        need = min(3, len(groups)) if groups else 0
        if n_quiz < need:
            problems.append(
                f"带检查点的节只有 {n_quiz},至少 {need}(材料共 {len(groups)} 组)"
            )
        # 材料组覆盖:covers 显式指认,集合差直接点名(比标题模糊匹配可靠)
        if groups:
            covered: set[str] = set()
            for s in sections:
                if not isinstance(s, dict):
                    continue
                for item in str(s.get("covers", "")).replace("，", ",").split(","):
                    covered.add(_covers_key(item))
            missing = [g for g in groups if _covers_key(g) not in covered]
            if missing:
                problems.append(f"材料组未被任何节覆盖:{missing[:5]}")
        checks = [s.get("goal_check") for s in sections
                  if isinstance(s, dict) and s.get("goal_check")]
        if any(not _valid_goal_check(c) for c in checks):
            problems.append("goal_check 必须含非空 question 与 pass_rule")
        if any(s.get("goal_check") and not s.get("has_quiz")
               for s in sections if isinstance(s, dict)):
            problems.append("目标应用题所在节必须 has_quiz=true")
        required_plan = state.get("required_plan")
        if required_plan:
            preserved = [{k: sec.get(k) for k in ("id", "heading", "has_quiz", "covers")}
                         for sec in sections if isinstance(sec, dict)]
            original = [{k: sec.get(k) for k in ("id", "heading", "has_quiz", "covers")}
                        for sec in required_plan]
            if preserved != original:
                problems.append("恢复时只补 goal_check,原节 id/顺序/标题/覆盖与测验约定不得变更")
        if learning_goal and not checks:
            problems.append("大纲目标须有至少一道应用题 goal_check,逐项覆盖目标所要求的操作")
        if problems and not learning_goal and state["plan_reviews"] > 2 and not state["course_id"]:
            # 两次人审路径都走不通 → 静态模板兜底,循环绝不卡在规划上
            plan = _template_plan(groups, str(state.get("subtopic") or "本课"))
            state["plan"] = plan
            return (
                "(两次规划未过校验,已改用默认规划,照它写,别再 submit_plan):\n"
                + json.dumps(plan, ensure_ascii=False)
            )
        if problems:
            return "(规划有问题,重排后再 submit_plan):\n- " + "\n- ".join(problems)

        plan = [
            {
                "id": str(s.get("id", f"s{i}")),
                "heading": str(s.get("heading", ""))[:40],
                "has_quiz": bool(s.get("has_quiz")),
                "covers": str(s.get("covers", "")),
                **({"goal_check": s["goal_check"]} if s.get("goal_check") else {}),
            }
            for i, s in enumerate(sections)
            if isinstance(s, dict)
        ]
        # 人审(仅交互 tty;生成中心 auto 直接照单)。意见只喂回重排一次。
        if sys.stdin.isatty():
            print("\n课程规划(书页节序):")
            for i, s in enumerate(plan, 1):
                mark = " ◆" if s["has_quiz"] else ""
                print(f"  {i}. {s['heading']}{mark}")
            raw = input("回车照单 / 输入修改意见: ").strip()
            if raw and state["plan_reviews"] <= 2:
                state["plan_reviews"] += 1
                return f"(学员对规划有意见,按它重排后再 submit_plan):{raw}"
        if state["course_id"]:
            _save_plan(state["course_id"], plan, groups, job_binding, learning_goal)
        state["plan"] = plan
        return (
            f"规划通过({len(plan)} 节 / {n_quiz} 检查点)。"
            + ("继续:write_section 按规划补齐。" if state["course_id"]
               else "继续:init_course → write_section 逐节写。")
        )

    def init_course(  # noqa: A002
        id: str,
        title: str,
        scenario: str,
        source_notes: list[str],
        depends_on: list[dict[str, Any]] | None = None,
    ) -> str:
        if state["plan"] is None:
            return "(还没 submit_plan,先规划再建课件)"
        if job_binding:
            id = str(job_binding["course_id"])  # 后台任务预留,不靠模型命名辨认归属
        p = _course_path(id)
        if p.exists():
            return f"(课件 {id} 已存在,换个 id 或先删旧文件)"
        # depends_on 即时校验(与 write_page 单页校验同一自纠风格:错了当场反馈):
        # 自依赖/悬空 id/缺 reason 直接打回重交;合法才落盘。上限 2 门,先修链宁短勿长。
        deps: list[dict[str, str]] = []
        problems: list[str] = []
        existing_ids = _course_ids()
        for d in depends_on or []:
            did = str(d.get("id", "")).strip() if isinstance(d, dict) else ""
            reason = str(d.get("reason", "")).strip() if isinstance(d, dict) else ""
            if not did:
                problems.append("有条目缺 id")
            elif did == id:
                problems.append(f"「{did}」是本课自己,自依赖没有意义")
            elif did not in existing_ids:
                problems.append(f"先修 id「{did}」不存在——只许用速览清单里的 id")
            elif not reason:
                problems.append(f"先修「{did}」缺 reason,一句话写为什么先学它")
            elif any(x["id"] == did for x in deps):
                continue  # 重复条目静默去重
            else:
                deps.append({"id": did, "reason": reason})
        if len(deps) > 2:
            problems.append(f"先修给了 {len(deps)} 门,至多 2 门——留最不可或缺的")
        if problems:
            return (
                "(depends_on 有问题,课件未创建;改好重新 init_course):\n- "
                + "\n- ".join(problems)
            )
        # source_notes 语义=材料路径(vault 相对路径或原料文件),溯源/课表关联靠它。
        # 确定性覆盖:模型爱填小节标题之类的噪音,一律不认(实测踩过)
        if material_path:
            source_notes = [material_path]
        course: dict[str, Any] = {
            "id": id,
            "title": title,
            "scenario": scenario,
            "version": 2,  # 书页课件(顶层版本标记,v2 唯一真相)
            "meta": {
                "source_notes": source_notes,
                "publication_required": True,
                "topic": material_topic,  # 课程库分组钥匙,harness 确定性写入
                # 来源确定性带入:材料里的调研来源 harness 直接写进 meta.sources(有据链路终点)
                "sources": [
                    {"id": s.get("id", i), "title": str(s.get("title", ""))[:80],
                     "url": str(s.get("url", ""))}
                    for i, s in enumerate(material_sources, 1)
                ],
                "evidence": evidence_items or [],
                # 先修建议是教学判断,归模型;合法性归上面的即时校验 + 收笔终验
                "depends_on": deps,
                "duration_min": None,
            },
            "sections": [],
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        if job_binding:
            course["meta"].update(job_binding_id=job_binding["id"],
                                  job_kind=job_binding["kind"], job_target=job_binding["target"])
        _save_plan(id, state["plan"], groups, job_binding, learning_goal)
        p.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
        state["course_id"] = id
        dep_msg = (
            "、".join(f"{d['id']}({d['reason'][:20]})" for d in deps) if deps else "无先修"
        )
        _op_log(id, "init", f"建骨架,先修:{dep_msg},计划 {len(state['plan'])} 节")
        return f"课件骨架已建:{p.name}。先修:{dep_msg}。现在按计划 write_section 逐节写。"

    def write_section(section: dict[str, Any]) -> str:
        if job_binding:
            from app.core.job_store import ensure_active

            ensure_active(job_binding)
        cid = state["course_id"]
        if state["plan"] is None:
            return "(还没 submit_plan,先规划)"
        if not cid:
            return "(还没 init_course,先建课件骨架)"
        try:
            Section.model_validate(section)  # 单节即时校验:错了当场反馈,别等终验
        except Exception as e:  # noqa: BLE001 校验反馈本身就是观测
            return f"(这节结构不对,改完重交:{e})"[:600]
        p = _course_path(cid)
        course = _load(p)
        if course is None:
            return "(课件文件读不回,重新 init_course)"
        # 旧半成品首次续写时补材料索引;已有索引保留,不改写既有证据结论。
        if evidence_items and not course.setdefault("meta", {}).get("evidence"):
            course["meta"]["evidence"] = evidence_items
            # 早期课件丢过 source_id,按同一材料的 URL 补回身份,不能拿数组序号重编号。
            source_ids = {str(s.get("url", "")): s.get("id", i)
                          for i, s in enumerate(material_sources, 1)}
            for source in course["meta"].get("sources", []):
                if source.get("id") is None and source.get("url") in source_ids:
                    source["id"] = source_ids[source["url"]]
        proof = course_evidence_report({
            "meta": course.get("meta", {}), "sections": [section],
        })
        if proof["errors"]:
            return "(证据引用有问题,该节未写入):\n- " + "\n- ".join(proof["errors"])
        # upsert-by-id:同 id = 替换该节(改错的原语),否则追加。
        sid = section.get("id")
        plan_ids = [s["id"] for s in state["plan"]]
        if sid not in plan_ids:
            return f"(节 id {sid} 不在规划中,请使用原规划 id:{plan_ids})"
        idx = next((i for i, sc in enumerate(course["sections"]) if sc.get("id") == sid), None)
        if idx is None:
            course["sections"].append(section)
            n_quiz = sum(
                1
                for sc in course["sections"]
                for b in sc.get("blocks", [])
                if b.get("type") == "quiz"
            )
            msg = (
                f"已写入第{len(course['sections'])}节({sid}),"
                f"计划 {len(state['plan'])} 节,已有 {n_quiz} 个检查点。"
            )
            _op_log(cid, "write", f"{sid} {str(section.get('heading', ''))[:24]}({msg[:40]})")
        else:
            course["sections"][idx] = section
            msg = f"已替换第{idx + 1}节({sid})。"
            _op_log(cid, "replace", f"{sid} {str(section.get('heading', ''))[:24]}")
        course["sections"].sort(key=lambda s: plan_ids.index(s["id"]))
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
        errors = r["errors"] + _plan_delivery_errors(course, state["plan"], learning_goal)
        head = ("❌ " if errors else "✅ ") + str(r["summary"])
        body = "".join(f"\n  ✗ {e}" for e in errors)
        warns = r["warnings"]
        # warning(quiz 配额提示/先修缺 reason 等)只放前 5 条,免得淹没 error
        if len(warns) > 5:
            n_more = len(warns) - 5
            warns = warns[:5] + [f"(其余 {n_more} 条 warning 略)"]
        body += "".join(f"\n  ⚠ {w}" for w in warns)
        verdict = r["summary"][:120] + (f"(err {len(errors)})" if errors else "")
        _op_log(cid, "validate", verdict)
        return str(head + body)

    tools = [
        {
            "name": "submit_plan",
            "description": "第一步:提交课程规划(节序),人审通过才能动笔。"
            "covers 显式指认该节覆盖的材料组名,保证每组都被覆盖。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "heading": {"type": "string"},
                                "has_quiz": {"type": "boolean"},
                                "goal_check": {
                                    "type": "object",
                                    "properties": {"question": {"type": "string"},
                                                   "pass_rule": {"type": "string"}},
                                    "required": ["question", "pass_rule"],
                                    "description": "目标应用题,正文给示例,写节时原样交付题与标准",
                                },
                                "covers": {
                                    "type": "string",
                                    "description": "该节覆盖的材料组名,逗号分隔",
                                },
                            },
                            "required": ["id", "heading", "has_quiz", "covers"],
                        },
                    },
                },
                "required": ["sections"],
            },
        },
        {
            "name": "init_course",
            "description": "建课件骨架(先于 write_section)。id 用子题英文短横线 slug。"
            "depends_on 按速览判断先修,必填(独立课给 [])。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "scenario": {"type": "string", "enum": ["自学", "复习", "对外"]},
                    "source_notes": {"type": "array", "items": {"type": "string"}},
                    "depends_on": {
                        "type": "array",
                        "description": "先修课列表,至多 2 门;每项含 id(速览里已有的)和 reason",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": ["id", "reason"],
                        },
                    },
                },
                "required": ["id", "title", "scenario", "source_notes"],
            },
        },
        {
            "name": "write_section",
            "description": "追加一节(完整节 JSON: id/heading/blocks,块型照菜单)。一次一节;"
            "重交同 id = 替换该节(改错用)。quiz 块 id 用「<节id>-cp」。",
            "input_schema": {
                "type": "object",
                "properties": {"section": {"type": "object"}},
                "required": ["section"],
            },
        },
        {
            "name": "validate_csl",
            "description": "校验当前课件,返回逐条可改的反馈。每写 2~3 节自查一次。",
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
        "submit_plan": lambda a: submit_plan(a.get("sections", [])),
        "init_course": lambda a: init_course(**a),
        "write_section": lambda a: write_section(a.get("section", {})),
        "validate_csl": lambda _a: validate_csl(),
        "read_notes": lambda a: read_notes(a["keyword"]),
    }
    return tools, dispatch, state


# ---------- 人审:先修建议确认(交互模式;生成中心 auto 直接落盘) ----------


def confirm_depends_on(course: dict[str, Any]) -> None:
    """课件出炉后、发布前给人看一眼先修建议:回车照单 / clear 清空 / 覆盖 id。

    覆盖格式:逗号分隔课 id(理由保留能对上的,新 id 记「人工标注」)。
    只改盘上文件的 meta.depends_on,学习路线的拓扑排序会自动跟随。
    """
    import sys

    deps = course.get("meta", {}).get("depends_on") or []
    if not deps or not sys.stdin.isatty():
        return
    print("\n先修建议(学习路线会按它排顺序):")
    for d in deps:
        print(f"   ← {d['id']}: {d.get('reason', '')}")
    raw = input("回车照单 / clear 清空 / 输入课 id 覆盖(逗号分隔): ").strip()
    if not raw:
        return
    if raw.lower() == "clear":
        course["meta"]["depends_on"] = []
    else:
        by_id = {d["id"]: d.get("reason", "") for d in deps}
        course["meta"]["depends_on"] = [
            {"id": x.strip(), "reason": by_id.get(x.strip(), "人工标注")}
            for x in raw.split(",")
            if x.strip()
        ]
    p = _course_path(str(course["id"]))
    p.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已更新:{p.name} meta.depends_on")


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
    evidence = {e["id"]: e for e in material_evidence(m)}
    body = ""
    for gi, g in enumerate(m.get("groups", []), 1):
        body += f"\n## {g.get('heading')}"
        for pi, pt in enumerate(g.get("points", []), 1):
            eid = f"g{gi}p{pi}"
            item = evidence[eid]
            sid = f"(源[{pt.get('source_id')}])" if pt.get("source_id") else ""
            body += f"\n- 证据[{eid}] {pt.get('text')}{sid}"
            if item["quote"]:
                body += f"\n  原文摘录:{item['quote']}"
            body += f"\n  摘录定位:{item['quote_status']} / 原料语义:{item['support']}"
            if item.get("reason"):
                body += f" / {item['reason']}"
    return head + body



# 续写 prompt(中断/取消后的课件,载盘上已有节继续写;不重新规划)
RESUME_PROMPT = """你在**续写**一份未完成的书页课件(它属于某条零基础学习路线,写到一半中断了)。

{position}

# 课件已有内容(保留已有节 id,需要修错时重交同 id)
{existing_sections}

# 恢复规划
{resume_plan}

# 续写材料(与已写部分同一来源,每条要点带来源 id)
{material}

# 学员已有课程
{existing}

# 任务:按恢复规划 write_section(不要 init_course)
- 已有节不要重写凑数;补齐规划中尚未交付的节,严格沿用规划 id 和顺序
- 规划要求测验的节必须有 quiz 和非空 pass_rule;已有节缺测验可重交同 id 修正
- validate_csl 会对照规划检查漏节、测验与顺序,全部通过才算交付

{shared_style}

# 检查点纪律(教学闸)
规划要求测验的节,节末放 quiz(id「<节id>-cp」),question 问关系/区别/步骤,
pass_rule 写具体可判标准。

# 流程
1. 已恢复规划则直接 write_section;历史课没有规划则先 submit_plan
2. 每写 2~3 节 validate_csl 自查
3. 终验通过后收笔说交付总结(不再调工具)"""


# ---------- 主循环 ----------


@observed("prep")
def run_prep(
    material: dict[str, Any],
    prev_subtopic: str | None = None,
    resume_course_id: str | None = None,
    *, source: str = "user",
    job_binding: dict[str, Any] | None = None,
    learning_goal: str = "",
    prerequisite_titles: list[str] | None = None,
    revision_feedback: str = "",
) -> dict[str, Any]:
    if resume_course_id and not learning_goal:
        saved_contract = _load(_plan_path(resume_course_id)) or {}
        learning_goal = str(saved_contract.get("learning_goal") or "")
    tools, dispatch, state = _make_tools(
        material.get("sources") or [],
        material_path=material.get("_material_path"),
        material_topic=str(material.get("topic")) or None,
        material_groups=[str(g.get("heading", "")) for g in material.get("groups", [])],
        job_binding=job_binding,
        evidence_items=material_evidence(material),
        learning_goal=learning_goal,
    )
    state["subtopic"] = str(material.get("subtopic") or "本课")  # 兜底模板用
    position = (
        f"本课在「{material.get('topic')}」学习框架中的位置:前一课讲了「{prev_subtopic}」,"
        f"开场用一句话承接它。" if prev_subtopic else "这是该主题的第一课。"
    )
    if prerequisite_titles is not None:
        position += (
            "\n大纲指定的唯一先修课程:" + ("、".join(prerequisite_titles) or "无,这是独立入口课")
            + "。此约束优先于已有课程速览;不能预设其他旧课的知识,所需概念在本课讲清。"
        )
    if learning_goal:
        position += (
            f"\n大纲学习目标(交付约束):{learning_goal}\n"
            "submit_plan 至少一节填 goal_check={question,pass_rule},要求学员实际完成目标操作,"
            "不能用解释必要性替代设计/实现任务。正文给完整示例,对应节原样写入该应用题与判分标准。"
        )
    if resume_course_id:
        # 续写模式(P7):载盘上已有节,RESUME_PROMPT 直接逐节续写
        rc = _load(_course_path(resume_course_id))
        if rc is None:
            raise ValueError(f"续写目标课件不存在: {resume_course_id}")
        state["course_id"] = resume_course_id
        plan_path = _plan_path(resume_course_id)
        saved = _load(plan_path)
        if plan_path.exists():
            # 损坏不能悄悄当作旧课重排,否则会丢失原交付约定。
            if saved is None or saved.get("course_id") != resume_course_id:
                raise ValueError(f"恢复规划损坏或课件 id 不匹配: {plan_path}")
            plan = saved.get("sections")
            if (
                saved.get("version") != 1 or not isinstance(plan, list) or not plan
                or any(not isinstance(s, dict)
                       or not isinstance(s.get("id"), str) or not s["id"].strip()
                       or not isinstance(s.get("heading"), str) or not s["heading"].strip()
                       or not isinstance(s.get("has_quiz"), bool)
                       or not isinstance(s.get("covers"), str)
                       or (s.get("goal_check") is not None
                           and not _valid_goal_check(s["goal_check"])) for s in plan)
                or len({s["id"] for s in plan}) != len(plan)
            ):
                raise ValueError(f"恢复规划格式无效: {plan_path}")
            saved_goal = saved.get("learning_goal", "")
            if saved_goal and saved_goal != learning_goal:
                raise ValueError("大纲学习目标已变化,拒绝沿用原规划;请先审阅目标差异")
            if learning_goal and not any(s.get("goal_check") for s in plan):
                state["required_plan"] = plan
                # 旧规划缺目标验收时允许补约定,已有节 id 仍由 submit_plan 保护。
                resume_plan = (
                    "旧规划缺目标应用题,先 submit_plan 补 goal_check,其他字段不变:\n"
                    + json.dumps(plan, ensure_ascii=False)
                )
                tools = [t for t in tools if t["name"] != "init_course"]
            else:
                state["plan"] = plan
                tools = [t for t in tools if t["name"] not in ("submit_plan", "init_course")]
            if state["plan"] is not None:
                resume_plan = ("已恢复原规划,不要重新规划或改 id:\n"
                               + json.dumps(plan, ensure_ascii=False))
        else:
            resume_plan = (
                "历史半成品没有保存规划。先 submit_plan 补交完整规划(3~9 节),"
                "必须包含所有已有节的原 id,并覆盖全部材料组,然后按规划补写。"
                "不得宣称恢复了旧规划。"
            )
            tools = [t for t in tools if t["name"] != "init_course"]
        # 暴露给模型的工具与实际可执行清单保持一致。
        dispatch = {t["name"]: dispatch[t["name"]] for t in tools}
        secs = rc.get("sections", [])
        existing_lines = (
            "\n".join(
                f"- {s.get('id')} | {s.get('heading', '')} | 块 {len(s.get('blocks', []))} 个"
                for s in secs
            )
            or "(尚无节)"
        )
        prompt = RESUME_PROMPT.format(
            position=position,
            existing_sections=(
                f"课件「{rc.get('title', '')}」已有 {len(secs)} 节:\n{existing_lines}"
            ),
            resume_plan=resume_plan,
            material=_render_material(material),
            existing=_course_brief(),
            shared_style=_SHARED_STYLE,
        )
    else:
        prompt = PREP_PROMPT.format(
            position=position,
            material=_render_material(material),
            existing=_course_brief(),
            shared_style=_SHARED_STYLE,
        )
    if revision_feedback:
        # 外部审查反馈是待处理数据,不继承裁判的对话或推理。
        prompt += ("\n发布审查发现以下问题,保留原规划,只重交相关节修订。"
                   "补证必须来自材料真实原文;不能把事实改标示例逃避核查:\n" + revision_feedback)
        prompt += "\n当前全文:\n" + json.dumps((rc or {}).get("sections", []), ensure_ascii=False)
    # 离线批量循环放宽单次超时:模型一轮会写几千 token 的规划+页 JSON,
    # 中转慢速时 60s 必掐死(实测 191s);chat 的 60s 交互护栏不受影响
    client = get_llm_client().with_options(timeout=240.0)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    tool_calls: list[dict[str, Any]] = []
    validate_failures = 0
    text_out = ""
    t0 = time.perf_counter()
    run_context(prompt=prompt, tools=tools,
                parameters={"max_tokens": 16384, "max_turns": MAX_TURNS})
    update_run(subtopic=str(material.get("subtopic", "")))

    def final_check() -> list[str] | None:
        """天然收笔后的强校验:不过打回(None=通过)。终止客观化的关键一步。"""
        if state["course_id"] is None:
            return ["还没 init_course——先建课件骨架"]
        course = _load(_course_path(state["course_id"]))
        if course is None:
            return ["课件文件读不回"]
        r = validate_course(course)
        errors = r["errors"] + _plan_delivery_errors(course, state["plan"], learning_goal)
        return errors or None

    for turn in range(MAX_TURNS):
        if job_binding:
            from app.core.job_store import ensure_active

            ensure_active(job_binding)
        update_run(turns=turn + 1)
        last_turn = turn == MAX_TURNS - 1
        resp = client.messages.create(
            model=settings.llm_model,
            max_tokens=16384,  # 5.3 实测:8192 被思考全烧光两连(零工具调用→重试,纯损耗)
            # 观测客户端返回 Any,dict messages 直传不再需要 ignore(历史上 SDK TypedDict 拒 dict)
            messages=messages,
            tools=[] if last_turn else tools,
        )
        u = resp.usage
        usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        update_run(usage=usage)
        text_out = "".join(b.text for b in resp.content if b.type == "text")

        if resp.stop_reason != "tool_use":
            errs = final_check()
            if errs is None:
                course = _load(_course_path(state["course_id"])) if state["course_id"] else None
                if course is not None:
                    trace_prep(
                        course_id=str(course["id"]),
                        subtopic=str(material.get("subtopic")),
                        sections=len(course.get("sections", [])),
                        validate_failures=validate_failures,
                        ok=True,
                        elapsed_s=time.perf_counter() - t0,
                        tool_calls=tool_calls,
                        usage=usage,
                    )
                    _op_log(
                        state["course_id"], "deliver",
                        f"终验通过:{len(course.get('sections', []))} 节交付",
                    )
                    return {"ok": True, "course": course, "report": text_out, "usage": usage}
                errs = ["课件文件读不回"]  # 校验过了文件却没了,罕见,打回重建
            validate_failures += 1
            update_run(validate_failures=validate_failures, validation_errors=errs)
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
                emit_call(b.name, dict(b.input))
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
            update_run(tool_calls=tool_calls, course_id=state["course_id"] or "")
            print(f"  [{b.name}] {str(out)[:200]}")  # CLI 实时可见,复盘不用翻盘上文件
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
        messages.append({"role": "user", "content": results})

    # 软着陆:交付当前版本(已写页都在盘上)
    cid = state["course_id"]
    course = _load(_course_path(cid)) if cid else None
    trace_prep(
        course_id=cid or "",
        subtopic=str(material.get("subtopic")),
        sections=len(course.get("sections", [])) if course else 0,
        validate_failures=validate_failures,
        ok=False,
        elapsed_s=time.perf_counter() - t0,
        tool_calls=tool_calls,
        usage=usage,
        error="MAX_TURNS 耗尽(软着陆,已写节都在盘上)",
    )
    return {"ok": False, "course": course, "report": text_out, "usage": usage}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="备课 Agent:材料/笔记 → CSL 课件")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--material", help="找资料产出的原料 JSON 路径(新课)")
    g.add_argument("--note", help="vault 笔记相对路径(复习)")
    g.add_argument("--resume", help="续写未完成课件(按课件 id)")
    ap.add_argument("--prev", help="前置子题名(位置感,开场承接)")
    a = ap.parse_args()

    if a.resume:
        # 续写:材料路径从课件 meta.source_notes 恢复(当初用哪份材料就接着用)
        rc = _load(_course_path(a.resume))
        if rc is None:
            raise SystemExit(f"课件不存在: {a.resume}")
        src = (rc.get("meta", {}).get("source_notes") or [None])[0]
        if not src:
            raise SystemExit("课件 meta.source_notes 为空,无法恢复材料")
        m = _load_material(src) if src.endswith(".json") else _material_from_note(src)
        m["_material_path"] = src
        r = run_prep(m, resume_course_id=a.resume)
    else:
        m = _load_material(a.material) if a.material else _material_from_note(a.note)
        m["_material_path"] = a.material or a.note  # vault 相对路径,课表关联靠它
        r = run_prep(m, prev_subtopic=a.prev)
    if r["ok"]:
        from app.services.tts_compile import publish_courses

        c = r["course"]
        secs = c.get("sections", [])
        n_quiz = sum(1 for s in secs for b in s.get("blocks", []) if b.get("type") == "quiz")
        print(f"\n✅ 课件已交付:courses/{c['id']}.csl.json")
        n_blocks = sum(len(s.get("blocks", [])) for s in secs)
        print(f"   {len(secs)} 节 · {n_blocks} 块 · {n_quiz} 检查点")
        srcs = c.get("meta", {}).get("sources", [])
        if srcs:
            print(f"   来源 {len(srcs)} 个(有据可查)")
        confirm_depends_on(c)
        publish_courses()
        print("前端已就绪,打开阅读器即可学习")
    else:
        print("\n⚠️ 软着陆:MAX_TURNS 耗尽,当前版本已落盘,人工接着审")
