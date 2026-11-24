"""发布前强制验收:结构/原文定位/最终正文语义,失败保留草稿与报告。"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.trace import digest
from app.services.csl_validator import validate_course
from app.services.evidence import course_evidence_report, material_evidence
from app.services.evidence_review import review_claims


class PublicationBlocked(RuntimeError):
    pass


def content_hash(course: dict[str, Any]) -> str:
    payload = copy.deepcopy(course)
    payload.setdefault("meta", {}).pop("publication_review", None)
    return digest(payload)


def report_path(course_id: str) -> Path:
    return settings.data_dir / "publication" / f"{course_id}.json"


def assert_publishable(course: dict[str, Any]) -> None:
    """只用可重复的程序核验决定发布；模型意见只作为诊断信号。"""
    path = report_path(str(course["id"]))
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicationBlocked("发布被拦截:缺少有效的最终课件审查报告") from exc
    summary = course.get("meta", {}).get("publication_review") or {}
    structure = validate_course(course, check_model_support=False)
    evidence = course_evidence_report(course, check_model_support=False)
    # 老报告没有新字段时不能兼容放行：旧的 model_reviewed 只说明模型曾经
    # 返回过结论，没有留下当前门禁所需的程序检查、快照与绑定指纹。
    program_status = report.get("program_status")
    checks = report.get("program_checks")
    checks_passed = isinstance(checks, list) and bool(checks) and all(
        isinstance(check, dict) and check.get("status") == "passed" for check in checks
    )
    items = [i for i in report.get("items", []) if isinstance(i, dict)]
    block_ids = {b["id"] for b in evidence["blocks"]}
    exemplary_ids = {b["id"] for b in evidence["blocks"] if b.get("exemplary")}
    if (
        program_status != "passed"
        or not checks_passed
        or structure.get("errors")
        or evidence.get("errors")
        or report.get("content_hash") != content_hash(course)
        or summary.get("report_hash") != digest(report)
        or report.get("publication_status", "allowed") != "allowed"
        or not items
        or {i.get("id") for i in items} != block_ids
        or len(items) != len(block_ids)
        or any(i.get("verdict") not in ("supported", "not_applicable") for i in items)
        or any(i.get("verdict") == "not_applicable" and i.get("id") not in exemplary_ids
               for i in items)
    ):
        raise PublicationBlocked(
            "发布被拦截:程序核验未通过、报告已失效或存在未获原文支撑的内容,请查看依据报告"
        )


def is_review_draft(course: dict[str, Any]) -> bool:
    """新课从建骨架起即为草稿;历史未审课保留兼容展示。"""
    meta = course.get("meta") or {}
    if not meta.get("publication_required") and not meta.get("publication_review"):
        return False
    try:
        assert_publishable(course)
    except (PublicationBlocked, ValueError, TypeError, KeyError):
        return True
    return False


def _normalize_model_review(
    value: object, claims: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """把模型输出整理成诊断记录；模型格式和结论不参与程序门禁。"""
    diagnostics: list[str] = []
    raw = value if isinstance(value, dict) else {}
    if not isinstance(value, dict):
        diagnostics.append("模型语义审查未返回对象")
    raw_items = raw.get("items")
    if not isinstance(raw_items, list):
        raw_items = []
        if value:
            diagnostics.append("模型语义审查没有返回有效的逐块结果")

    expected = {str(claim["id"]) for claim in claims}
    accepted = {"supported", "partial", "unsupported", "uncertain", "not_applicable"}
    items_by_id: dict[str, dict[str, str]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            diagnostics.append("模型语义审查包含格式无效的结果项")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or item_id not in expected:
            diagnostics.append("模型语义审查包含未知或无效的块 ID")
            continue
        if item_id in items_by_id:
            diagnostics.append(f"模型语义审查块 {item_id} 有重复结果")
            items_by_id.pop(item_id, None)
            continue
        verdict = item.get("verdict")
        reason = item.get("reason")
        if verdict not in accepted or not isinstance(reason, str) or not reason.strip():
            diagnostics.append(f"模型语义审查块 {item_id} 的结论或说明无效")
            continue
        items_by_id[item_id] = {
            "id": item_id,
            "verdict": verdict,
            "reason": reason.strip()[:1000],
        }

    items = []
    for claim in claims:
        claim_id = str(claim["id"])
        items.append(items_by_id.get(claim_id, {
            "id": claim_id,
            "verdict": "unreviewed",
            "reason": "模型未提供有效的逐块意见",
        }))
    if len(items_by_id) != len(expected):
        diagnostics.append("模型语义审查结果不完整；程序门禁仍按可复核证据独立判断")

    normalized: dict[str, Any] = {
        "reviewer": str(raw.get("reviewer") or "未记录模型"),
        "items": items,
    }
    for key in ("input_hash", "prompt_hash", "usage", "attempts", "elapsed_s", "error"):
        if key in raw and isinstance(raw[key], (str, int, float, dict, list)):
            normalized[key] = raw[key]
    if isinstance(raw.get("error"), str) and raw["error"]:
        diagnostics.append(f"模型语义审查调用异常：{raw['error'][:200]}")
    for item in items:
        if item["verdict"] in {"partial", "unsupported", "uncertain", "unreviewed"}:
            diagnostics.append(f"{item['id']} · {item['verdict']}：{item['reason']}")
    return normalized, diagnostics


def review_section(
    course: dict[str, Any], section: dict[str, Any], material: dict[str, Any],
    *, learning_goal: str = "",
) -> list[str]:
    """写节即审:单节逐块原文支撑,失败当场打回作者;通过则结论并入缓存供终审复用。

    claims 构造与 review_course 逐字段一致(块 id/text/exemplary + 同节证据上下文),
    终审按 claim 哈希直接复用写节结论,只重审改过的块。
    """
    if material.get("evidence_version") != 1:
        return ["原料未按 v1 证据格式保存(无可重验的原文快照);请重新调研生成材料"]
    evidence_report = course_evidence_report(
        {"meta": course.get("meta", {}), "sections": [section]}, check_model_support=False,
    )
    if evidence_report["errors"]:
        return list(evidence_report["errors"])
    try:
        original = {e["id"]: e for e in material_evidence(material)}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return [f"原文证据重验失败:{type(exc).__name__}"]
    refs = {eid for b in section.get("blocks", []) for eid in b.get("evidence_ids", [])}
    by_section = {section["id"]: {
        "heading": section.get("heading", ""),
        "evidence": [{k: original[eid][k] for k in
                      ("id", "source_id", "quote", "context", "source_hash")}
                     for eid in sorted(refs) if eid in original],
    }}
    claims = [
        {
            "id": b["id"],
            "text": b["text"],
            "exemplary": bool(b.get("exemplary")),
            "learning_goal": learning_goal,
            "section": by_section[b["id"].rsplit(":", 1)[0]],
        }
        for b in evidence_report["blocks"]
    ]
    checkpoint_path = report_path(str(course["id"])).with_suffix(".checkpoint.json")
    previous = None
    if checkpoint_path.exists():
        try:
            previous = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
    try:
        raw = review_claims(claims, course_mode=True, previous=previous)
    except Exception as exc:  # noqa: BLE001 审查服务不可用=该节不算过,打回重交
        return [f"语义审查服务异常,请稍后重交该节:{type(exc).__name__}"]
    review, _diagnostics = _normalize_model_review(raw, claims)
    exemplary_ids = {c["id"] for c in claims if c["exemplary"]}
    errors = []
    unresolved = []
    for item in review["items"]:
        if item["verdict"] == "not_applicable" and item["id"] not in exemplary_ids:
            errors.append(f"{item['id']} 未申报示例(exemplary=true)的块不能用不适用代替核对")
            continue
        if item["verdict"] == "unreviewed":
            # 审查服务重试后仍未出意见(疑似持续抖动):这不是内容错误,
            # 不能盲打回让作者改——明示服务原因,作者稍后重交同一节即可。
            unresolved.append(f"{item['id']} 审查服务未能给出意见(已自动重试),请稍后重交本节")
            continue
        if item["verdict"] not in ("supported", "not_applicable"):
            errors.append(f"{item['id']} [{item['verdict']}] {item['reason']}")
    if unresolved:
        return unresolved + errors  # 服务原因优先展示,作者不拿空意见改内容
    if errors:
        return errors
    # 通过:结论按块内容哈希并入缓存;终审复用,只重审改动过的块。
    merged_items = [i for i in (previous or {}).get("items", [])
                    if i.get("id") not in {c["id"] for c in claims}]
    merged = {
        "reviewer": raw.get("reviewer", "model"),
        "items": merged_items + review["items"],
        "claim_hashes": {**(previous or {}).get("claim_hashes", {}),
                         **raw.get("claim_hashes", {})},
    }
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    return []


def review_course(
    course: dict[str, Any], material: dict[str, Any], *, learning_goal: str = ""
) -> dict[str, Any]:
    """每次审查完整最终内容,不继承作者会话;不等价于人工复核。"""
    structure = validate_course(course, check_model_support=False)
    errors = list(structure["errors"])
    evidence_report = course_evidence_report(course, check_model_support=False)
    errors.extend(evidence_report["errors"])
    material_errors: list[str] = []
    try:
        if material.get("evidence_version") != 1:
            material_errors.append(
                "原料未按 v1 证据格式保存(无可重验的原文快照),不能支撑可溯源审查;请重新调研生成材料"
            )
        original = {e["id"]: e for e in material_evidence(material)}
        source_urls = {s.get("id", i): s.get("url")
                       for i, s in enumerate(material.get("sources", []), 1)}
        for i, source in enumerate(course.get("meta", {}).get("sources", []), 1):
            if source_urls.get(source.get("id", i)) != source.get("url"):
                material_errors.append(f"来源 {source.get('id', i)} URL 与原料不一致")
        for item in course.get("meta", {}).get("evidence", []):
            source = original.get(item["id"], {})
            if source.get("quote_status") != "matched" or any(
                item.get(k) != source.get(k)
                for k in ("source_id", "quote", "context", "source_hash")
            ):
                material_errors.append(f"证据 {item['id']} 未获原文快照验证或已变化")
        if not original:
            material_errors.append("缺少可验证的原文证据")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        material_errors.append(f"原文证据重验失败:{type(exc).__name__}")
    errors.extend(material_errors)
    review: dict[str, Any] = {"items": []}
    model_diagnostics: list[str] = []
    claims: list[dict[str, Any]] = []
    verdict_errors: list[str] = []
    if not errors:
        # 未直接关联的题目/图示也送审,提供同节依据,避免自动漏审。
        by_section: dict[str, dict[str, Any]] = {}
        for section in course.get("sections", []):
            refs = {eid for b in section["blocks"] for eid in b.get("evidence_ids", [])}
            by_section[section["id"]] = {
                "heading": section["heading"],
                "evidence": [
                    {key: original[eid].get(key) for key in
                     ("id", "source_id", "quote", "context", "source_hash")}
                    for eid in sorted(refs) if eid in original
                ],
            }
        claims = [
            {
                "id": b["id"],
                "text": b["text"],
                "exemplary": bool(b.get("exemplary")),
                "learning_goal": learning_goal,
                "section": by_section[b["id"].rsplit(":", 1)[0]],
            }
            for b in evidence_report["blocks"]
        ]
        print(f"发布审查:最终课件 {len(claims)} 块逐项核对", flush=True)
        checkpoint_path = report_path(str(course["id"])).with_suffix(".checkpoint.json")
        previous = None
        if checkpoint_path.exists():
            try:
                previous = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = None

        def checkpoint(value: dict[str, Any]) -> None:
            from app.core.job_progress import ensure_job_active

            ensure_job_active()
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = checkpoint_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            temporary.replace(checkpoint_path)

        try:
            raw_review = review_claims(
                claims, course_mode=True, previous=previous, checkpoint=checkpoint,
            )
        except Exception as exc:  # noqa: BLE001 模型故障不再放行:逐块结论缺位=程序错误
            raw_review = {"error": type(exc).__name__, "items": []}
        review, model_diagnostics = _normalize_model_review(raw_review, claims)
        # 逐块原文支撑硬闸:supported 才放行;not_applicable 仅限写作时申报的示例块。
        expected = {c["id"] for c in claims}
        actual = [i["id"] for i in review["items"]]
        if set(actual) != expected or len(actual) != len(expected):
            verdict_errors.append("最终课件审查缺项或重复,禁止发布")
        exemplary_ids = {c["id"] for c in claims if c["exemplary"]}
        for item in review["items"]:
            if item["verdict"] == "not_applicable" and item["id"] not in exemplary_ids:
                verdict_errors.append(
                    f"{item['id']} 未申报示例(exemplary=true)的块不能用不适用代替核对"
                )
            if item["verdict"] not in ("supported", "not_applicable"):
                verdict_errors.append(f"{item['id']} [{item['verdict']}] {item['reason']}")
    errors.extend(verdict_errors)
    model_items = review.get("items", [])
    model_review_status = "not_run"
    if claims:
        reviewed_count = sum(item["verdict"] != "unreviewed" for item in model_items)
        if reviewed_count == len(claims):
            model_review_status = "completed"
        elif reviewed_count:
            model_review_status = "partial"
        else:
            model_review_status = "failed"
    program_status = "passed" if not errors else "blocked"
    publication_status = "allowed" if program_status == "passed" else "blocked"
    status = "program_passed" if publication_status == "allowed" else "blocked"
    program_checks = [
        {
            "id": "structure",
            "label": "课件结构与规则",
            "status": "passed" if not structure["errors"] else "failed",
            "detail": "；".join(structure["errors"]) or structure["summary"],
        },
        {
            "id": "evidence_links",
            "label": "块与证据关联",
            "status": "passed" if not evidence_report["errors"] else "failed",
            "detail": "；".join(evidence_report["errors"])
            or (f"{evidence_report['linked_blocks']} / "
                f"{evidence_report['total_blocks']} 块有证据关联"),
        },
        {
            "id": "source_snapshots",
            "label": "来源 URL 与原文快照",
            "status": "passed" if not material_errors else "failed",
            "detail": "；".join(material_errors) or "来源、摘录、上下文和快照指纹一致",
        },
        {
            "id": "block_support",
            "label": "逐块原文支撑",
            "status": "passed" if not verdict_errors else "failed",
            "detail": "；".join(verdict_errors[:3]) if verdict_errors else (
                f"{sum(i['verdict'] == 'supported' for i in review['items'])}"
                f" / {len(review['items'])} 块获原文支撑" if review["items"]
                else "未运行(存在更早的程序错误)"
            ),
        },
    ]
    report = {
        "version": 1,
        "course_id": course["id"],
        "content_hash": content_hash(course),
        "status": status,
        "program_status": program_status,
        "model_review_status": model_review_status,
        "publication_status": publication_status,
        "program_checks": program_checks,
        "model_diagnostics": model_diagnostics,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "errors": errors,
        "items": review["items"],
        "model_review": review,
    }
    from app.core.job_progress import ensure_job_active

    ensure_job_active()
    path = report_path(str(course["id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    # 保存历次失败便于定位,最新报告用于发布校验。
    history = path.with_name(f"{course['id']}-{digest(report)[:12]}.json")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    history.write_text(text, encoding="utf-8")
    temp = path.with_suffix(".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)
    course.setdefault("meta", {})["publication_review"] = {
        "status": status,
        "program_status": program_status,
        "model_review_status": model_review_status,
        "content_hash": report["content_hash"],
        "report_hash": digest(report),
        "reviewed_at": report["reviewed_at"],
        "reviewer": review.get("reviewer", "未完成"),
    }
    (settings.courses_dir / f"{course['id']}.csl.json").write_text(
        json.dumps(course, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def ensure_publication(
    course: dict[str, Any],
    material: dict[str, Any],
    *,
    learning_goal: str = "",
    job_binding: dict[str, Any] | None = None,
    prerequisite_titles: list[str] | None = None,
) -> dict[str, Any]:
    """首次审查加最多两轮定点修订;只重用绑定课件,不重建规划。"""
    from app.agent.prep import run_prep

    if not learning_goal:
        # learning_goal 参与 claim 字节(digest)——漏传会让写节即审 checkpoint 的
        # 逐块哈希全部失配,终审退化为全量重审(E2E 实测 11 分钟白审)。
        # 盘上规划存有权威值,调用方没传就从那里补齐,保证缓存键稳定。
        from app.agent.prep import _load, _plan_path

        saved = _load(_plan_path(str(course["id"])))
        if saved:
            learning_goal = str(saved.get("learning_goal", "") or "")

    for attempt in range(3):
        if job_binding:
            from app.core.job_store import ensure_active

            ensure_active(job_binding)
        report = review_course(course, material, learning_goal=learning_goal)
        if job_binding:
            ensure_active(job_binding)
        if report.get("publication_status") == "allowed":
            assert_publishable(course)
            if attempt == 0:
                from app.core.job_progress import emit_progress

                emit_progress("revision", "skipped", "本次审查通过，无需定点修订")
            return course
        # 审查服务失败不能让作者猜着改,保留草稿供恢复审查。
        if attempt == 2 or not report["errors"]:
            break
        print(f"发布审查未通过,定点修订 {attempt + 1}/2", flush=True)
        from app.core.job_progress import emit_progress

        emit_progress("revision", "running", f"定点修订 {attempt + 1}/2："
                      f"{len(report['errors'])} 项待处理意见")
        # 修订单节微任务:按待修块归属的节拆分,每节独立一轮 run_prep——
        # E2E 实证全课上下文+自由收笔权会让作者连写数轮长分析而不动手
        # (4 次 16k 输出零 write_section);微任务只投喂待修节,无处可分析。
        error_text = "\n".join(report["errors"])
        # errors 形如 "s2-model-gaps:1 [partial] …";取块 id 冒号前的节 id。
        section_ids = sorted({
            e.split(":", 1)[0]
            for e in report["errors"] if ":" in e and not e.startswith(("第", "课件"))
        })
        course_sections = {s.get("id"): s for s in course.get("sections", [])}
        targets = [sid for sid in section_ids if sid in course_sections] or list(course_sections)
        course = dict(course)
        for sid in targets:
            section_feedback = "\n".join(
                e for e in report["errors"] if e.startswith(f"{sid}:")
            ) or error_text
            result = run_prep(
                material,
                resume_course_id=str(course["id"]),
                learning_goal=learning_goal,
                job_binding=job_binding,
                prerequisite_titles=prerequisite_titles,
                revision_feedback=section_feedback,
                revision_section_id=sid,
            )
            if not result.get("ok"):
                break
            course = result["course"]
        else:
            emit_progress("revision", "completed", "修订章节已保存，等待重新审查")
    raise PublicationBlocked(f"课程未发布:最终课件审查未通过;报告 {report_path(str(course['id']))}")
