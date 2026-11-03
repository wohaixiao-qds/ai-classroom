"""LLM 客户端工厂——共享 harness 基础设施(一处创建,处处复用)。

接缝中立:调用方只依赖 get_llm_client(),不直接 import anthropic。
当前内脏用 anthropic SDK 连智谱(智谱说 Anthropic 兼容协议,借力而非绑定);
将来若接异构格式(OpenAI 原生等),只换本文件内部,调用方零改动。

调用观测层(P4 第五轮追加):包一层 messages.create,每次模型调用打
「⋯ 模型调用 #N…」/「✓ #N 完成 · 耗时 · tokens」两行——备课/调研跑在后台
子进程(python -u),这些行实时进任务日志,页面 JobFeed 就能看到模型全程
在干活(此前两次阶段 print 之间的几分钟是全静默的)。只观测不改行为:
流式(messages.stream)与其余属性原样透传。
"""

from __future__ import annotations

import time
from typing import Any

from anthropic import Anthropic

from app.core.config import settings

# 模块级单例:避免每次调用新建连接
_client: Anthropic | None = None
_call_no = 0  # 模型调用序号(后台子进程内 = 本任务第几次调用)


def _fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


class _ObservedMessages:
    """拦截 messages.create 打心跳行;stream 等其余方法透传。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def create(self, **kwargs: Any) -> Any:
        global _call_no
        _call_no += 1
        n = _call_no
        t0 = time.time()
        print(f"⋯ 模型调用 #{n}…", flush=True)
        resp = self._inner.create(**kwargs)
        dt = time.time() - t0
        usage = getattr(resp, "usage", None)
        it = int(getattr(usage, "input_tokens", 0) or 0)
        ot = int(getattr(usage, "output_tokens", 0) or 0)
        print(
            f"✓ 模型调用 #{n} 完成 · {dt:.1f}s · in {_fmt_tokens(it)} / out {_fmt_tokens(ot)} tok",
            flush=True,
        )
        return resp

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _ObservedClient:
    """观测包装:with_options 派生的客户端同样带观测;其余透传。"""

    def __init__(self, inner: Anthropic) -> None:
        self._inner = inner
        self.messages = _ObservedMessages(inner.messages)

    def with_options(self, **kwargs: Any) -> _ObservedClient:
        return _ObservedClient(self._inner.with_options(**kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def get_llm_client() -> Any:
    """返回项目统一的 LLM 客户端(带调用观测层)。base_url/key 由 settings 决定,换模型改配置即可。"""
    global _client
    if _client is None:
        _client = Anthropic(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "not-set",
            timeout=60.0,  # 时间维度终止:单次调用超 60s 判死,补 MAX_TURNS(次数)兜不住的盲区
        )
    return _ObservedClient(_client)
