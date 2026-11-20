"""课件音频编译 + 发布(M3)——确定性编译器,不是 agent 工具。

按图纸判据「需要再决策才进循环」:TTS 无模型决策,是纯编译步骤
(设计方案 §四的「编译器:CSL → 音频」)。逻辑源自 P1 scripts/tts_gen.py,
收编为进程内服务供备课管线收尾自动调用;CLI 保留为薄壳。

发布(publish_courses):课件+音频同步到前端 vite public——
手动同步是坑(实测踩过:agent 写了后端,前端 404),管线必须自动做。
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from app.core.config import settings
from app.schemas.csl import Course
from app.tts.edge import EdgeTTSProvider
from app.tts.provider import TTSProvider


async def _gen(provider: TTSProvider, path: Path) -> tuple[int, int]:
    """为课件每句讲稿生成 mp3,路径回写 audio 字段。断点续跑;连续 3 失败止损。"""
    course = Course.model_validate_json(path.read_text(encoding="utf-8"))
    audio_dir = path.parent / "audio" / course.id
    audio_dir.mkdir(parents=True, exist_ok=True)

    done = fail = 0
    stop = False
    for page in course.pages:
        if stop:
            break
        for i, sent in enumerate(page.script):
            if sent.audio and (audio_dir / Path(sent.audio).name).exists():
                continue  # 断点续跑:已有音频跳过
            out = audio_dir / f"{page.id}-s{i}.mp3"
            try:
                await provider.synthesize(sent.text, out)
            except RuntimeError as e:
                fail += 1
                print(f"  ❌ {page.id} s{i}: {e}")
                if fail >= 3:
                    print("连续失败过多,停止(大概率 403/限流,稍后续跑或换 provider)")
                    stop = True
                continue
            sent.audio = str(out.relative_to(path.parent))
            done += 1

    path.write_text(course.model_dump_json(indent=2), encoding="utf-8")
    return done, fail


def compile_course_audio(course_id: str, provider: TTSProvider | None = None) -> tuple[int, int]:
    """编译一门课的音频(入口)。返回 (新生成数, 失败数)。"""
    path = settings.courses_dir / f"{course_id}.csl.json"
    if json.loads(path.read_text(encoding="utf-8")).get("version") == 2:
        print(f"↩ {course_id}: v2 书页课件无音频(P6 拍板 TTS 砍留位),跳过编译")
        return (0, 0)
    return asyncio.run(_gen(provider or EdgeTTSProvider(), path))


def publish_courses(course_id: str | None = None) -> None:
    """课件+音频 → 前端 public(全量镜像,幂等)。"""
    dst = settings.web_public_courses
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    from app.core.job_store import incomplete_course_ids

    pending = incomplete_course_ids()
    pending.discard(course_id or "")  # 当前课程已终验,发布成功后 runner 才置 done

    def ignore(directory: str, names: list[str]) -> set[str]:
        if Path(directory) != settings.courses_dir:
            return set()
        return {name for name in names if name.endswith(".csl.json")
                and name.removesuffix(".csl.json") in pending}

    shutil.copytree(settings.courses_dir, dst, ignore=ignore)
    print(f"✅ 已发布到前端: {dst}")
