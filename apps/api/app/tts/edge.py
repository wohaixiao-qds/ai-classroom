"""edge-tts 实现：微软 Edge 朗读接口（免费）。

已知风险（2026-08 实测结论见 docs）：
- 大陆 IP 频繁 403（Sec-MS-GEC 校验）——重试 + 退避缓解，持续失败则切 zhipu
- 限流约单 IP 30 次/分钟——句间加延时
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

from app.tts.provider import TTSProvider

_RETRY = 3
_RETRY_BACKOFF = 2.0  # 秒，指数递增
_GAP_BETWEEN = 2.5  # 句间间隔，防限流


class EdgeTTSProvider(TTSProvider):
    name = "edge"

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural") -> None:
        self.voice = voice

    async def synthesize(self, text: str, out_path: Path) -> Path:
        last_err: Exception | None = None
        for attempt in range(1, _RETRY + 1):
            try:
                await edge_tts.Communicate(text, self.voice).save(str(out_path))
                if out_path.stat().st_size > 0:
                    await asyncio.sleep(_GAP_BETWEEN)
                    return out_path
                msg = "输出文件为空"
                raise RuntimeError(msg)
            except Exception as e:  # noqa: BLE001 统一退避后重试
                last_err = e
                await asyncio.sleep(_RETRY_BACKOFF**attempt)
        msg = f"edge-tts 连续 {_RETRY} 次失败: {last_err}"
        raise RuntimeError(msg)
