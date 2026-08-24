"""课件音频编译 CLI:uv run python scripts/tts_gen.py <course_id>

薄壳:逻辑在 app/services/tts_compile.py(备课管线收尾同源调用)。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.tts_compile import compile_course_audio, publish_courses

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: tts_gen.py <course_id>")
        sys.exit(2)
    done, fail = compile_course_audio(sys.argv[1])
    print(f"完成: 新生成 {done}, 失败 {fail}")
    publish_courses()
