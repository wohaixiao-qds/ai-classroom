"""LLM 客户端工厂——共享 harness 基础设施(一处创建,处处复用)。

接缝中立:调用方只依赖 get_llm_client(),不直接 import anthropic。
当前内脏用 anthropic SDK 连智谱(智谱说 Anthropic 兼容协议,借力而非绑定);
将来若接异构格式(OpenAI 原生等),只换本文件内部,调用方零改动。
"""

from __future__ import annotations

from anthropic import Anthropic

from app.core.config import settings

# 模块级单例:避免每次调用新建连接
_client: Anthropic | None = None


def get_llm_client() -> Anthropic:
    """返回项目统一的 LLM 客户端。base_url/key 由 settings 决定,换模型改配置即可。"""
    global _client
    if _client is None:
        _client = Anthropic(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "not-set",
        )
    return _client
