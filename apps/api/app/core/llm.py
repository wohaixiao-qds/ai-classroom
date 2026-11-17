"""LLM 客户端工厂——共享 harness 基础设施(一处创建,处处复用)。

接缝中立:调用方只依赖 get_llm_client(),不直接 import anthropic。
当前内脏用 anthropic SDK 连智谱(智谱说 Anthropic 兼容协议,借力而非绑定);
将来若接异构格式(OpenAI 原生等),只换本文件内部,调用方零改动。

调用观测层(P4 第五轮追加):包一层 messages.create,每次模型调用打
「⋯ 模型调用 #N…」/「✓ #N 完成 · 耗时 · tokens」两行——备课/调研跑在后台
子进程(python -u),这些行实时进任务日志,页面 JobFeed 就能看到模型全程
在干活(此前两次阶段 print 之间的几分钟是全静默的)。

双 key 故障切换(2026-11-17):主 key 认证/配额失败(401/403/429)时自动切
备用 key(ZHIPU_API_KEY_BACKUP)并重试本次调用,进程内记住切换状态不再回头
撞主 key。只切「key 用不了」类错误——超时/连接/5xx 属网络或中转问题,换
key 无用,不切。create 与 stream 构造期都兜(stream 的 HTTP 请求在构造时
同步发起,认证错当场抛出);流中途的网络断连不属此列。key 日志只打掩码。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from anthropic import Anthropic
from anthropic._exceptions import AuthenticationError, PermissionDeniedError, RateLimitError

from app.core.config import settings

# 模块级单例:避免每次调用新建连接;key 切换时置 None 触发重建
_client: Anthropic | None = None
_using_backup = False  # 已切到备用 key(持续性故障,切了就不回头撞主 key)
_call_no = 0  # 模型调用序号(后台子进程内 = 本任务第几次调用)

_KEY_ERRORS = (AuthenticationError, PermissionDeniedError, RateLimitError)


def _mask(key: str) -> str:
    return f"{key[:8]}…{key[-4:]}" if len(key) > 16 else "…"


def _build() -> Anthropic:
    """按当前 key 状态构建底层客户端(切换=清 _client 后由这里重建)。"""
    backup = settings.zhipu_api_key_backup
    key = backup if _using_backup and backup else settings.llm_api_key
    return Anthropic(
        base_url=settings.llm_base_url,
        api_key=key or "not-set",
        timeout=60.0,  # 时间维度终止:单次调用超 60s 判死,补 MAX_TURNS(次数)兜不住的盲区
    )


def _raw_client() -> Anthropic:
    global _client
    if _client is None:
        _client = _build()
    return _client


def _switch_to_backup(err: Exception) -> bool:
    """主 key 认证/配额失败 → 切备用 key 并重建客户端。返回是否切成功。"""
    global _client, _using_backup
    backup = settings.zhipu_api_key_backup
    if not backup:
        print(
            f"✗ LLM key 不可用({_mask(settings.llm_api_key or '?')},"
            f"{err.__class__.__name__})且未配置备用 key",
            flush=True,
        )
        return False
    _using_backup = True
    _client = None  # 清单例,_raw_client() 重建时用备用 key
    print(
        f"⚠ 主 LLM key 不可用({err.__class__.__name__}),"
        f"已切换备用 key({_mask(backup)})重试本次调用,后续调用直接走备用 key",
        flush=True,
    )
    return True


def _guard(call: Callable[[], Any]) -> Any:
    """key 故障切换守卫:认证/配额类异常切备用 key 重试一次;备 key 再失败原样抛。"""
    global _using_backup
    try:
        return call()
    except _KEY_ERRORS as e:
        if _using_backup or not settings.zhipu_api_key_backup:
            raise
        if not _switch_to_backup(e):
            raise
        return call()


def _fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


class _ObservedMessages:
    """拦截 messages.create 打心跳行;stream 同样带 key 切换守卫;其余方法透传。"""

    def __init__(self, options: dict[str, Any]) -> None:
        self._options = options

    def _messages(self) -> Any:
        c = _raw_client()
        return c.with_options(**self._options).messages if self._options else c.messages

    def create(self, **kwargs: Any) -> Any:
        global _call_no
        _call_no += 1
        n = _call_no
        t0 = time.time()
        print(f"⋯ 模型调用 #{n}…", flush=True)
        messages = self._messages()

        def call() -> Any:
            return messages.create(**kwargs)

        resp = _guard(call)
        dt = time.time() - t0
        usage = getattr(resp, "usage", None)
        it = int(getattr(usage, "input_tokens", 0) or 0)
        ot = int(getattr(usage, "output_tokens", 0) or 0)
        print(
            f"✓ 模型调用 #{n} 完成 · {dt:.1f}s · in {_fmt_tokens(it)} / out {_fmt_tokens(ot)} tok",
            flush=True,
        )
        return resp

    def stream(self, **kwargs: Any) -> Any:
        messages = self._messages()

        def call() -> Any:
            return messages.stream(**kwargs)

        return _guard(call)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._messages(), name)


class _ObservedClient:
    """观测包装:with_options 派生同样带观测与 key 切换;其余透传。"""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self._options = options or {}

    @property
    def messages(self) -> _ObservedMessages:
        return _ObservedMessages(self._options)

    def with_options(self, **kwargs: Any) -> _ObservedClient:
        return _ObservedClient({**self._options, **kwargs})

    def __getattr__(self, name: str) -> Any:
        c = _raw_client()
        return getattr(c.with_options(**self._options) if self._options else c, name)


def get_llm_client() -> Any:
    """返回项目统一的 LLM 客户端(带调用观测层+双 key 故障切换)。
    base_url/key 由 settings 决定,换模型改配置即可。"""
    return _ObservedClient()
