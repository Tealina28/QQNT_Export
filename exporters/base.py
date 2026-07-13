"""
导出器基类

定义所有导出器的统一接口。
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from parser.models import ParsedMessage, ParsedMember


class BaseExporter(ABC):
    """导出器基类"""

    streams_messages = False
    supports_incremental_messages = False

    def __init__(self, output_path: Path, config: dict[str, Any]):
        """初始化导出器

        Args:
            output_path: 输出文件路径
            config: 配置字典
        """
        self.output_path = Path(output_path)
        self.config = config

    @abstractmethod
    def export(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
        messages: list[ParsedMessage]
    ):
        """导出数据

        Args:
            meta: 元信息字典（包含 name, platform, type 等）
            members: 成员列表
            messages: 消息列表
        """
        pass

    @abstractmethod
    def get_file_extension(self) -> str:
        """返回文件扩展名（如 '.json', '.jsonl'）"""
        pass

    def ensure_output_dir(self):
        """确保输出目录存在"""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def start_stream(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
    ) -> None:
        raise NotImplementedError

    def write_message(self, message: ParsedMessage) -> None:
        raise NotImplementedError

    def finish_stream(self) -> None:
        raise NotImplementedError

    def abort_stream(self) -> None:
        pass
