"""课件音频预生成 CLI：python scripts/tts_gen.py courses/xxx.csl.json

为课件每句讲稿生成 mp3，路径与时长回写 CSL JSON（audio 字段）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas.csl import Course
from app.tts.edge import EdgeTTSProvider
from app.tts.provider import TTSProvider


async def gen(provider: TTSProvider, path: Path) -> None:
    course = Course.model_validate_json(path.read_text(encoding="utf-8"))
    audio_dir = path.parent / "audio" / course.id
    audio_dir.mkdir(parents=True, exist_ok=True)

    done = fail = 0
    for page in course.pages:
        for i, sent in enumerate(page.script):
            if sent.audio and (audio_dir / Path(sent.audio).name).exists():
                continue  # 断点续跑：已有音频跳过
            out = audio_dir / f"{page.id}-s{i}.mp3"
            try:
                await provider.synthesize(sent.text, out)
                sent.audio = str(out.relative_to(path.parent))
                done += 1
                print(f"  ✅ {page.id} s{i}")
            except RuntimeError as e:
                fail += 1
                print(f"  ❌ {page.id} s{i}: {e}")
                if fail >= 3:
                    print("连续失败过多，停止（大概率 403/限流，考虑切换 provider）")
                    break
        if fail >= 3:
            break

    path.write_text(course.model_dump_json(indent=2), encoding="utf-8")
    print(f"完成: 新生成 {done}, 失败 {fail}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: tts_gen.py <course.csl.json>")
        sys.exit(2)
    asyncio.run(gen(EdgeTTSProvider(), Path(sys.argv[1])))
