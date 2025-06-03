from collections import defaultdict
from datetime import datetime
from json import dump
from pathlib import Path

from export.txt_exporter.elements import *

__all__ = ["C2cJsonExporter", "GroupJsonExporter"]


class ExportManager:
    def __init__(self):
        self.export_queue: dict[Path:list[dict]] = defaultdict(list)

    def add(self, path: Path, content: dict):
        self.export_queue[path].append(content)

    def __del__(self):
        for path in self.export_queue:
            dump(
                self.export_queue[path],
                path.open(mode="w+", encoding="utf-8"),
                ensure_ascii=False,
                indent=2,
            )


c2c_manager = ExportManager()
group_manager = ExportManager()


class BaseExporter:
    def __init__(self, message):
        self.message = message
        self.readable_time = datetime.fromtimestamp(message.time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        self.contents = []
        self.elements_map = {
            1: Text,
            2: Image,
            3: File,
            4: Voice,
            5: Video,
            6: Emoji,
            8: Notice,
            9: RedPacket,
            10: Application,
            21: Call,
            26: Feed,
        }

    def _extract(self):
        for element in self.message.elements.elements:
            self.contents.append(self._extract_single(element))

    def _extract_single(self, element):
        if element.type in self.elements_map:
            return self.elements_map[element.type](element).content
        elif element.type == 7:
            result = self._extract_single(element.quotedElement)
            if result[0]:
                result = ("[被引用的消息]" + result[0], result[1])
            else:
                result = ("[被引用的消息]", result[1])
            return result

        return None, None


class C2cJsonExporter(BaseExporter):
    def __init__(self, message):
        super().__init__(message)
        if message.sender_flag == 0:
            self.direction = "收"
        elif message.sender_flag in (1, 2):
            self.direction = "发"
        elif message.sender_flag == 8:
            self.direction = "转发"
        else:
            self.direction = "未知"

    def write(self, output_path: Path):
        self._extract()

        if self.message.profile_info:
            filename = self.message.profile_info.remark or self.message.profile_info.nickname
        elif self.message.mapping:
            filename = self.message.mapping.qq_num
        else:
            filename = self.message.interlocutor_num

        json_path = output_path / f"{filename}.json"
        msg_dict = {
            "time": self.readable_time,
            "direction": self.direction,
            "contents": self.contents,
        }
        c2c_manager.add(json_path, msg_dict)


class GroupJsonExporter(BaseExporter):
    def __init__(self, message):
        super().__init__(message)

    def write(self, output_path: Path):
        self._extract()
        json_path = output_path / f"{self.message.mixed_group_num}.json"

        msg_dict = {
            "time": self.readable_time,
            "sender": (
                    self.message.group_name_card
                    or self.message.nickname
                    or self.message.sender_num
            ),
            "sender_qq": self.message.sender_num,
            "contents": self.contents,
        }
        group_manager.add(json_path, msg_dict)
