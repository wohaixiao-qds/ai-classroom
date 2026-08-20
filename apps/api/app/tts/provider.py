"""TTS Provider 抽象：讲稿文本 → 音频文件。

实现方（edge.py / zhipu.py）负责具体合成；上层只依赖本接口。
设计要点：403/限流重试退避在实现方内部消化，上层无感。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSProvider(ABC):
    """文本转语音提供方。"""

    name: str

    @abstractmethod
    async def synthesize(self, text: str, out_path: Path) -> Path:
        """把 text 合成为音频写入 out_path，返回路径。

        实现方必须：内部重试（403/限流），失败抛 RuntimeError 带原因。
        """
        raise NotImplementedError
