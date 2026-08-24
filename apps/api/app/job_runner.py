"""后台任务体(M5):uvicorn spawn 的子进程入口。

用法(由 executor.start_job 调,不直接跑):
    python -m app.job_runner request_prep  <vault笔记相对路径>
    python -m app.job_runner request_research <待探主题名>

状态机回写 catalog_actions:queued → running → done(detail=课件id) / failed(detail=原因)。
注意:同一时间同一 target 只应有一个在跑(路由层已挡重复)。
"""

from __future__ import annotations

import sys
from typing import Any

from app.core.catalog_store import set_status


def _run() -> str:
    kind, target = sys.argv[1], sys.argv[2]
    set_status(target, "running")
    result: dict[str, Any]
    if kind == "request_prep":
        from app.agent.prep import _material_from_note, run_prep

        material = _material_from_note(target)
        material["_material_path"] = target  # vault 相对路径,课表关联靠它
        result = run_prep(material)
    elif kind == "request_research":
        from app.agent.prep import run_prep
        from app.agent.research import research_material

        material = research_material(target, target)  # 待探项本身就是子题
        result = run_prep(material)
    else:
        return f"未知任务类型: {kind}"

    if not result.get("ok"):
        return "备课未通过校验(软着陆),产物在 courses/ 可人工接着审"
    course = result["course"]

    from app.services.tts_compile import compile_course_audio, publish_courses

    compile_course_audio(str(course["id"]))
    publish_courses()
    return str(course["id"])


if __name__ == "__main__":
    try:
        detail = _run()
    except Exception as e:  # noqa: BLE001 后台任务:任何异常都要落状态,不能静默死掉
        set_status(sys.argv[2], "failed", str(e)[:200])
        print(f"FAILED: {e}")
        sys.exit(1)
    set_status(sys.argv[2], "done", detail)
    print(f"DONE: {detail}")
