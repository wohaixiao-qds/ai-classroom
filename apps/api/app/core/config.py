"""运行配置:从环境变量 / 密钥文件读,缺省给本地开发的合理值。

全项目密钥统一放仓库根 config/secrets.env(已 gitignore),格式:
    ZHIPU_API_KEY=xxx
    SEARCH_API_KEY=xxx
    # KB_DIR=/path/to/vault  # 可选,默认指向学习知识库
模板见 config/secrets.env.example。
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_API_ROOT = Path(__file__).resolve().parent.parent.parent  # apps/api/
_REPO_ROOT = _API_ROOT.parent.parent  # 仓库根(config/ 密钥目录所在)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / "config" / "secrets.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM: 智谱 Anthropic 兼容接口(换 Claude/Z.ai 只改 base_url)
    # 国内站: https://open.bigmodel.cn/api/anthropic
    # 国际站: https://api.z.ai/api/anthropic
    llm_base_url: str = "https://open.bigmodel.cn/api/anthropic"
    zhipu_api_key: str = ""  # 环境变量/.env 里的 ZHIPU_API_KEY 自动注入
    zhipu_api_key_backup: str = ""  # 备用 key(ZHIPU_API_KEY_BACKUP):主 key 认证/配额失败时自动切换
    # 2026-11-03 用户拍板全站 glm-5.3(对照实验:备课质量代差明显,时长 +22% 可接受)。
    # 5.3 特性:思考常开不可关,经 anthropic 兼容端点 reasoning_effort/budget 均无效,
    # 思考块与文本共吃 max_tokens 预算——各调用点预算见各文件(重思考任务 16384 起)
    llm_model: str = "glm-5.3"

    # 搜索(博查 → AnySearch → Tavily,tools.search_provider 自动选择;ZHIPU_API_KEY 仅作 LLM 用)
    search_api_key: str = ""
    anysearch_api_key: str = ""
    tavily_api_key: str = ""

    # 知识库(只读!)
    kb_dir: Path = Path("/Users/zhangyu/CodeDevelopment/学习知识库")

    # 课件目录 / 轨迹落盘(Eval 层)
    courses_dir: Path = _API_ROOT / "courses"
    traces_dir: Path = _API_ROOT / "traces"
    data_dir: Path = _API_ROOT / "data"  # SQLite 等运行时数据(gitignore)

    @property
    def web_public_courses(self) -> Path:
        """前端静态课件目录(vite public):编译产物发布目标。"""
        return _API_ROOT.parent / "web" / "public" / "courses"

    @property
    def llm_api_key(self) -> str:
        """别名:业务代码用 llm_api_key,环境变量名保持 ZHIPU_API_KEY。"""
        return self.zhipu_api_key


settings = Settings()
