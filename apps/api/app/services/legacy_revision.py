"""老课复审的隔离工作流。

老课不能直接套用新课的 ``review_course``：审查期间可能超时、修订只完成一半，
而学习进度又依赖原课程 ID。本模块把候选、原件备份、报告和晋级记录放在
``data/revisions``，只有完整通过发布门禁的候选才原子替换正式文件。
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from app.core.config import settings
from app.core.trace import digest
from app.services.publication import (
    PublicationBlocked,
    assert_publishable,
    report_path,
    review_course,
)


class RevisionBlocked(RuntimeError):
    """候选不满足复审或晋级条件。"""


@dataclass(frozen=True)
class RevisionPaths:
    root: Path

    @property
    def candidate(self) -> Path:
        return self.root / "candidate.csl.json"

    @property
    def original(self) -> Path:
        return self.root / "original.csl.json"

    @property
    def material(self) -> Path:
        return self.root / "material.json"

    @property
    def manifest(self) -> Path:
        return self.root / "revision.json"

    @property
    def report(self) -> Path:
        return self.root / "publication.json"

    @property
    def original_published(self) -> Path:
        return self.root / "original.published.csl.json"


def _paths(root: Path) -> RevisionPaths:
    return RevisionPaths(root=root)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RevisionBlocked(f"无法读取 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RevisionBlocked(f"JSON 顶层不是对象: {path}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _checkpoint_ids(course: dict[str, Any]) -> list[str]:
    return list(_checkpoint_snapshots(course))


def _checkpoint_snapshots(course: dict[str, Any]) -> dict[str, dict[str, str]]:
    units = course.get("sections") or course.get("pages") or []
    result: dict[str, dict[str, str]] = {}
    if course.get("version") == 2:
        for section in units:
            for block in section.get("blocks", []):
                if block.get("type") == "quiz" and block.get("id"):
                    result[str(block["id"])] = {
                        "question": str(block.get("question") or ""),
                        "pass_rule": str(block.get("pass_rule") or ""),
                    }
    else:
        for page in units:
            checkpoint = page.get("checkpoint")
            if checkpoint:
                result[str(page["id"])] = {
                    "question": str(checkpoint.get("question") or ""),
                    "pass_rule": str(checkpoint.get("pass_rule") or ""),
                }
    return result


def _revision_root(course_id: str, revision_id: str | None) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = revision_id or uuid4().hex[:10]
    return Path(settings.data_dir) / "revisions" / f"{stamp}-{course_id}-{suffix}"


def create_revision(
    course_id: str,
    *,
    material_path: Path | None = None,
    revision_id: str | None = None,
) -> RevisionPaths:
    """创建不可变原件备份和可编辑候选。

    ``material_path`` 会复制到复审目录，之后调研员可以替换这份副本补齐快照，
    不会修改知识库或正式 research 原料。
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", course_id):
        raise RevisionBlocked("课程 id 无效")
    if revision_id is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", revision_id):
        raise RevisionBlocked("复审 id 无效")
    source = settings.courses_dir / f"{course_id}.csl.json"
    if not source.exists():
        raise RevisionBlocked(f"正式课件不存在: {course_id}")
    original = _load(source)
    if str(original.get("id")) != course_id:
        raise RevisionBlocked("文件名与课件 id 不一致，拒绝猜测修复")
    if material_path is not None and not material_path.exists():
        raise RevisionBlocked(f"原料不存在: {material_path}")
    root = _revision_root(course_id, revision_id)
    paths = _paths(root)
    root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source, paths.original)
    shutil.copy2(source, paths.candidate)
    published = settings.web_public_courses / source.name
    published_hash = None
    if _copy_if_exists(published, paths.original_published):
        published_hash = digest(paths.original_published.read_bytes().decode("utf-8"))
    if material_path is not None:
        shutil.copy2(material_path, paths.material)
    manifest = {
        "version": 1,
        "course_id": course_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "candidate",
        "original_source_hash": digest(paths.original.read_bytes().decode("utf-8")),
        "original_published_hash": published_hash,
        "checkpoint_before": _checkpoint_ids(original),
        "checkpoint_after": _checkpoint_ids(original),
        "checkpoint_snapshots_before": _checkpoint_snapshots(original),
        "checkpoint_snapshots_after": _checkpoint_snapshots(original),
        "checkpoint_mapping": {i: i for i in _checkpoint_ids(original)},
        "relearning_required": [],
    }
    _write(paths.manifest, manifest)
    return paths


@contextmanager
def _isolated_workspace(paths: RevisionPaths) -> Iterator[None]:
    """让 publication.py 的现有写入逻辑只触及复审目录。"""
    old_data, old_courses = settings.data_dir, settings.courses_dir
    isolated_data = paths.root / "data"
    isolated_courses = paths.root / "courses"
    isolated_data.mkdir(parents=True, exist_ok=True)
    isolated_courses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths.candidate, isolated_courses / paths.candidate.name)
    settings.data_dir, settings.courses_dir = isolated_data, isolated_courses
    try:
        yield
    finally:
        settings.data_dir, settings.courses_dir = old_data, old_courses


def _manifest(paths: RevisionPaths) -> dict[str, Any]:
    manifest = _load(paths.manifest)
    course_id = manifest.get("course_id")
    if not isinstance(course_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", course_id
    ):
        raise RevisionBlocked("复审清单中的课程 id 无效")
    snapshots = manifest.get("checkpoint_snapshots_before")
    if not isinstance(snapshots, dict) or any(
        not isinstance(key, str)
        or not isinstance(value, dict)
        or not isinstance(value.get("question"), str)
        or not isinstance(value.get("pass_rule"), str)
        for key, value in snapshots.items()
    ):
        raise RevisionBlocked("复审清单缺少有效检查点语义快照；请重新创建复审")
    return manifest


def _apply_learning_state(
    course_id: str,
    mapping: dict[str, str],
    relearn: list[str],
    revision_id: str,
) -> None:
    """迁移活跃答题/复习记录；重做记录先归档，保证可追溯。"""
    import sqlite3

    database = settings.data_dir / "classroom.db"
    if not database.exists():
        return
    with sqlite3.connect(database) as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        active_tables = [
            table for table in ("learning_grades", "checkpoint_mastery") if table in tables
        ]
        for old, new in mapping.items():
            if old == new:
                continue
            for table in active_tables:
                if connection.execute(
                    f"SELECT 1 FROM {table} WHERE course_id=? AND page_id=? LIMIT 1",
                    (course_id, new),
                ).fetchone():
                    raise RevisionBlocked(
                        f"检查点映射目标 {new} 已有学习记录；不能合并掌握度"
                    )
        if relearn and active_tables:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS legacy_revision_learning_archive ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, revision_id TEXT NOT NULL, "
                "source_table TEXT NOT NULL, course_id TEXT NOT NULL, page_id TEXT NOT NULL, "
                "record_json TEXT NOT NULL, archived_at TEXT NOT NULL)"
            )
            archived_at = datetime.now(UTC).isoformat()
            for page_id in relearn:
                for table in active_tables:
                    rows = connection.execute(
                        f"SELECT * FROM {table} WHERE course_id=? AND page_id=?",
                        (course_id, page_id),
                    ).fetchall()
                    columns = [column[0] for column in connection.execute(
                        f"PRAGMA table_info({table})"
                    )]
                    for row in rows:
                        connection.execute(
                            "INSERT INTO legacy_revision_learning_archive "
                            "(revision_id,source_table,course_id,page_id,record_json,archived_at) "
                            "VALUES(?,?,?,?,?,?)",
                            (revision_id, table, course_id, page_id,
                             json.dumps(dict(zip(columns, row, strict=True)), ensure_ascii=False),
                             archived_at),
                        )
                    connection.execute(
                        f"DELETE FROM {table} WHERE course_id=? AND page_id=?",
                        (course_id, page_id),
                    )
        for old, new in mapping.items():
            if old == new:
                continue
            if "learning_grades" in active_tables:
                rows = connection.execute(
                    "SELECT id,result FROM learning_grades WHERE course_id=? AND page_id=?",
                    (course_id, old),
                ).fetchall()
                for row_id, raw_result in rows:
                    result = json.loads(raw_result)
                    if isinstance(result, dict):
                        result["page_id"] = new
                    connection.execute(
                        "UPDATE learning_grades SET page_id=?,result=? WHERE id=?",
                        (new, json.dumps(result, ensure_ascii=False), row_id),
                    )
            if "checkpoint_mastery" in active_tables:
                connection.execute(
                    "UPDATE checkpoint_mastery SET page_id=? WHERE course_id=? AND page_id=?",
                    (new, course_id, old),
                )


def _material_files(course: dict[str, Any]) -> list[Path]:
    """只定位 data/research 下的原料副本，不跟随 source_notes 读任意路径。"""
    root = settings.data_dir.resolve()
    found: set[Path] = set()
    for note in (course.get("meta") or {}).get("source_notes", []):
        if not isinstance(note, str) or not note.endswith(".material.json"):
            continue
        path = Path(note)
        candidates = [path] if path.is_absolute() else [root / path]
        if not path.is_absolute() and path.parts[:1] == ("data",):
            candidates.append(root.joinpath(*path.parts[1:]))
        if not path.is_absolute():
            candidates.append(root / "research" / path.name)
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if resolved.is_relative_to(root) and resolved.is_file():
                    found.add(resolved)
                    break
            except OSError:
                continue
    return sorted(found)


def _legacy_review_state(course_id: str, current_hash: str | None) -> str:
    revisions = settings.data_dir / "revisions"
    entries: list[dict[str, Any]] = []
    if revisions.is_dir():
        for manifest_path in revisions.glob("*/revision.json"):
            try:
                manifest = _load(manifest_path)
            except RevisionBlocked:
                continue
            if manifest.get("course_id") == course_id:
                entries.append(manifest)
    if not entries:
        return "unreviewed"
    latest = max(entries, key=lambda item: str(item.get("created_at", "")))
    status = latest.get("status")
    if status == "promoted":
        return "promoted" if latest.get("candidate_hash") == current_hash else "stale"
    if status == "reviewed":
        return "reviewed"
    if status == "candidate":
        return "candidate"
    return "blocked"


def audit_legacy_courses() -> dict[str, Any]:
    """只读盘点当前课件的新门禁状态与老课复审状态。"""
    courses: list[dict[str, Any]] = []
    for path in sorted(settings.courses_dir.glob("*.csl.json")):
        row: dict[str, Any] = {
            "course_id": path.name.removesuffix(".csl.json"),
            "title": "",
            "version": None,
            "checkpoints": 0,
            "evidence_items": 0,
            "matched_evidence_items": 0,
            "material_files_found": 0,
            "materials_with_snapshots": 0,
            "publication_report_exists": False,
            "publication_report_status": None,
            "publication_gate": "blocked",
            "publication_block_reason": "正式课件审查报告缺失",
            "legacy_review_status": "unreviewed",
            "blockers": [],
        }
        try:
            course = _load(path)
        except RevisionBlocked as exc:
            row["blockers"].append(str(exc))
            row["legacy_review_status"] = "blocked"
            courses.append(row)
            continue
        course_id = str(course.get("id", ""))
        row["course_id"] = course_id
        row["title"] = str(course.get("title", ""))
        row["version"] = course.get("version", 1)
        row["checkpoints"] = len(_checkpoint_snapshots(course))
        evidence = (course.get("meta") or {}).get("evidence") or []
        row["evidence_items"] = len(evidence)
        row["matched_evidence_items"] = sum(
            1 for item in evidence
            if isinstance(item, dict) and item.get("quote_status") == "matched"
        )
        materials = []
        for material_path in _material_files(course):
            try:
                material = _load(material_path)
            except RevisionBlocked:
                continue
            materials.append(material)
        row["material_files_found"] = len(materials)
        row["materials_with_snapshots"] = sum(
            1 for material in materials if material.get("evidence_version") == 1
            and bool(material.get("source_snapshots"))
        )
        current_hash = digest(path.read_bytes().decode("utf-8"))
        row["legacy_review_status"] = _legacy_review_state(course_id, current_hash)
        pub_path = report_path(course_id)
        if pub_path.exists():
            row["publication_report_exists"] = True
            try:
                report = _load(pub_path)
                row["publication_report_status"] = report.get("status")
                assert_publishable(course)
                row["publication_gate"] = "allowed"
                row["publication_block_reason"] = None
            except (RevisionBlocked, PublicationBlocked, ValueError, TypeError, KeyError) as exc:
                row["publication_block_reason"] = str(exc)
        if row["legacy_review_status"] != "promoted":
            row["blockers"].append("尚未通过老课复审晋级")
        if row["publication_gate"] != "allowed":
            row["blockers"].append(str(row["publication_block_reason"]))
        if not row["evidence_items"]:
            row["blockers"].append("课件未保存可复核的原文证据项")
        elif row["matched_evidence_items"] != row["evidence_items"]:
            row["blockers"].append("部分原文摘录没有可定位快照")
        if row["material_files_found"] and not row["materials_with_snapshots"]:
            row["blockers"].append("找到历史原料，但未保存可重验的完整正文快照")
        courses.append(row)
    statuses = [course["legacy_review_status"] for course in courses]
    return {
        "courses": courses,
        "summary": {
            "total": len(courses),
            "unreviewed": statuses.count("unreviewed"),
            "candidate": statuses.count("candidate"),
            "reviewed": statuses.count("reviewed"),
            "promoted": statuses.count("promoted"),
            "stale": statuses.count("stale"),
            "publication_allowed": sum(c["publication_gate"] == "allowed" for c in courses),
        },
    }


def review_revision(paths: RevisionPaths, *, material_path: Path | None = None) -> dict[str, Any]:
    """在候选目录执行完整发布审查，并把报告留在候选目录。"""
    manifest = _manifest(paths)
    candidate = _load(paths.candidate)
    if str(candidate.get("id")) != manifest.get("course_id"):
        raise RevisionBlocked("候选修改了课程 id；老课复审必须保留原 id")
    material = _load(material_path or paths.material)
    with _isolated_workspace(paths):
        report = review_course(candidate, material, learning_goal=str(candidate.get("title", "")))
        candidate = _load(settings.courses_dir / f"{manifest['course_id']}.csl.json")
        isolated_report = settings.data_dir / "publication" / f"{manifest['course_id']}.json"
        if isolated_report.exists():
            shutil.copy2(isolated_report, paths.report)
    _write(paths.candidate, candidate)
    manifest.update(
        status="reviewed" if report.get("status") == "model_reviewed" else "blocked",
        review_status=report.get("status"),
        reviewed_at=report.get("reviewed_at"),
        report_hash=digest(report),
        candidate_hash=digest(paths.candidate.read_bytes().decode("utf-8")),
        checkpoint_after=_checkpoint_ids(candidate),
        checkpoint_snapshots_after=_checkpoint_snapshots(candidate),
    )
    _write(paths.manifest, manifest)
    return cast(dict[str, Any], report)


def _checkpoint_mapping(
    before: dict[str, dict[str, str]],
    after: dict[str, dict[str, str]],
    requested: dict[str, str] | None,
    relearning_required: list[str] | None,
) -> tuple[dict[str, str], list[str]]:
    mapping = {key: value for key, value in (requested or {}).items()}
    relearn = set(relearning_required or [])
    overlap = set(mapping) & relearn
    if overlap:
        raise RevisionBlocked(f"检查点不能同时映射和标记重做: {', '.join(sorted(overlap))}")
    for checkpoint_id, snapshot in before.items():
        if (
            after.get(checkpoint_id) == snapshot
            and checkpoint_id not in mapping
            and checkpoint_id not in relearn
        ):
            mapping[checkpoint_id] = checkpoint_id
    invalid_relearn = sorted(relearn - before.keys())
    if invalid_relearn:
        raise RevisionBlocked(f"重做标记引用未知旧检查点: {', '.join(invalid_relearn)}")
    invalid = [
        f"{old}->{new}" for old, new in mapping.items()
        if old not in before or new not in after
    ]
    if invalid:
        raise RevisionBlocked(f"检查点映射无效: {', '.join(invalid)}")
    destinations = list(mapping.values())
    if len(destinations) != len(set(destinations)):
        raise RevisionBlocked("多个旧检查点不能合并到同一个新检查点")
    missing = [checkpoint_id for checkpoint_id in before if checkpoint_id not in mapping]
    unmarked = [checkpoint_id for checkpoint_id in missing if checkpoint_id not in relearn]
    if unmarked:
        raise RevisionBlocked(
            "有检查点被删除或改名，必须逐个提供映射或显式标记重做: " + ", ".join(unmarked)
        )
    return mapping, [checkpoint_id for checkpoint_id in before if checkpoint_id in relearn]


def promote_revision(
    paths: RevisionPaths,
    *,
    checkpoint_mapping: dict[str, str] | None = None,
    relearning_required: list[str] | None = None,
) -> dict[str, Any]:
    """把已通过审查的候选原子替换正式源和前端副本。"""
    manifest = _manifest(paths)
    if manifest.get("status") != "reviewed" or manifest.get("review_status") != "model_reviewed":
        raise RevisionBlocked("候选未通过最终课件审查，不能晋级")
    candidate = _load(paths.candidate)
    course_id = str(manifest.get("course_id"))
    if candidate.get("id") != course_id:
        raise RevisionBlocked("候选课程 id 已变化")
    candidate_hash = digest(paths.candidate.read_bytes().decode("utf-8"))
    if candidate_hash != manifest.get("candidate_hash"):
        raise RevisionBlocked("候选在审查后发生变化；请重新审查")
    report = _load(paths.report)
    if digest(report) != manifest.get("report_hash"):
        raise RevisionBlocked("复审报告在审查后发生变化；请重新审查")
    current = settings.courses_dir / f"{course_id}.csl.json"
    current_hash = digest(current.read_bytes().decode("utf-8")) if current.exists() else None
    if current_hash != manifest.get("original_source_hash"):
        raise RevisionBlocked("正式源课件已变化，候选过期；请从最新版本重新创建复审")
    web_target = settings.web_public_courses / current.name
    expected_published_hash = manifest.get("original_published_hash")
    if expected_published_hash is None:
        if web_target.exists():
            raise RevisionBlocked("正式课件此前没有发布副本，但现在已出现；候选过期")
    else:
        published_hash = (
            digest(web_target.read_bytes().decode("utf-8")) if web_target.exists() else None
        )
        if published_hash != expected_published_hash:
            raise RevisionBlocked("已发布副本在复审期间发生变化；请从最新版本重新创建复审")
    with _isolated_workspace(paths):
        isolated_report = settings.data_dir / "publication" / f"{course_id}.json"
        if not paths.report.exists():
            raise RevisionBlocked("复审目录缺少 publication.json")
        isolated_report.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths.report, isolated_report)
        try:
            assert_publishable(candidate)
        except PublicationBlocked as exc:
            raise RevisionBlocked(str(exc)) from exc
    before = manifest.get("checkpoint_snapshots_before", {})
    after = _checkpoint_snapshots(candidate)
    mapping, relearn = _checkpoint_mapping(
        before, after, checkpoint_mapping, relearning_required,
    )
    report_target = settings.data_dir / "publication" / f"{course_id}.json"
    report_target.parent.mkdir(parents=True, exist_ok=True)
    source_target = current
    replacements = [
        (source_target, paths.candidate.read_bytes()),
        (report_target, paths.report.read_bytes()),
    ]
    if web_target.exists() or settings.web_public_courses.exists():
        replacements.append((web_target, paths.candidate.read_bytes()))
    staged: list[tuple[Path, Path]] = []
    originals: dict[Path, bytes | None] = {}
    for target, content in replacements:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(content)
        staged.append((temporary, target))
        originals[target] = target.read_bytes() if target.exists() else None
    try:
        for temporary, target in staged:
            os.replace(temporary, target)
        _apply_learning_state(course_id, mapping, relearn, paths.root.name)
    except OSError:
        for target, original in originals.items():
            if original is None:
                target.unlink(missing_ok=True)
            else:
                rollback = target.with_name(f".{target.name}.{uuid4().hex}.rollback")
                rollback.write_bytes(original)
                os.replace(rollback, target)
        raise
    except BaseException:
        for target, original in originals.items():
            if original is None:
                target.unlink(missing_ok=True)
            else:
                rollback = target.with_name(f".{target.name}.{uuid4().hex}.rollback")
                rollback.write_bytes(original)
                os.replace(rollback, target)
        raise
    manifest.update(
        status="promoted",
        promoted_at=datetime.now(UTC).isoformat(),
        checkpoint_after=after,
        checkpoint_mapping=mapping,
        relearning_required=relearn,
    )
    _write(paths.manifest, manifest)
    return manifest


def load_revision(path: Path) -> RevisionPaths:
    root = path if path.is_dir() else path.parent
    paths = _paths(root)
    for required in (paths.candidate, paths.original, paths.manifest):
        if not required.exists():
            raise RevisionBlocked(f"复审目录缺少 {required.name}")
    return paths
