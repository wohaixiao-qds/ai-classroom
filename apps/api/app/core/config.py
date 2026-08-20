"""运行配置:从环境变量读,缺省给本地开发的合理值。

需要的环境变量(见 .env 或 shell):
- ZHIPU_API_KEY      智谱 API key(Anthropic 兼容接口)
- SEARCH_API_KEY     搜索 API key(博查)
- KB_DIR             知识库目录(只读)
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    # LLM: 智谱 Anthropic 兼容接口(换 Claude 只改这两行)
    llm_base_url: str = "https://open.bigmodel.cn/api/anthropic"
    llm_api_key: str = os.environ.get("ZHIPU_API_KEY", "")
    llm_model: str = "glm-4.6"

    # 搜索(博查)
    search_api_key: str = os.environ.get("SEARCH_API_KEY", "")

    # 知识库(只读!)
    kb_dir: Path = Path(
        os.environ.get(
            "KB_DIR",
            "/Users/zhangyu/CodeDevelopment/学习知识库",
        )
    )

    # 课件目录
    courses_dir: Path = Path(__file__).resolve().parent.parent.parent / "courses"

    # 轨迹落盘(Eval 层)
    traces_dir: Path = Path(__file__).resolve().parent.parent.parent / "traces"


settings = Settings()
