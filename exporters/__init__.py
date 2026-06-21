"""
Exporters Layer - 导出层

负责将解析后的数据导出为各种格式，插件化设计。
"""

from .base import BaseExporter
from .chatlab_json import ChatLabJSONExporter
from .chatlab_jsonl import ChatLabJSONLExporter
from .html import HTMLExporter

__all__ = [
    'BaseExporter',
    'ChatLabJSONExporter',
    'ChatLabJSONLExporter',
    'HTMLExporter',
]

# 导出器注册表
EXPORTER_MAP = {
    'chatlab_json': ChatLabJSONExporter,
    'chatlab_jsonl': ChatLabJSONLExporter,
    'html': HTMLExporter,
}
