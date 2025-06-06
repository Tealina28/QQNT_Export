from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .elements import *

__all__ = ["C2cTxtExporter", "GroupTxtExporter"]


class ExportManager:
    def __init__(self):
        self.export_queue: dict[Path:list] = defaultdict(list)

    def add(self, path: Path, content: str):
        self.export_queue[path].append(content)

    def __del__(self):
        for path in self.export_queue:
            with path.open(mode="w+", encoding="utf-8") as f:
                for content in self.export_queue[path]:
                    f.write(content)


c2c_manager = ExportManager()
group_manager = ExportManager()


class BaseExporter:
    def __init__(self, message):
        self.message = message
        self.readable_time = datetime.fromtimestamp(message.time).strftime("%Y-%m-%d %H:%M:%S")
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
            26: Feed
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


class C2cTxtExporter(BaseExporter):
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

    def write(self, output_path):
        self._extract()

        if self.message.profile_info:
            filename = self.message.profile_info.remark or self.message.profile_info.nickname
        elif self.message.mapping:
            filename = self.message.mapping.qq_num
        else:
            filename = self.message.interlocutor_num

        txt_path = output_path / f"{filename}.txt"

        content_str = f"""{self.readable_time} {self.direction}\n"""

        for content in self.contents:
            content_str += f"{content[0]}\n{content[1]}\n"

        content_str += "\n"

        c2c_manager.add(txt_path, content_str)


class GroupTxtExporter(BaseExporter):
    def __init__(self, message):
        super().__init__(message)

    def write(self, output_path):
        self._extract()

        if self.message.group_info:
            file_name = self.message.group_info.remark or self.message.group_info.name
        else:
            file_name = self.message.mixed_group_num

        if self.message.group_name_card:
            display_identity = self.message.group_name_card
        elif self.message.nickname:
            display_identity = self.message.nickname
        elif self.message.sender_profile:
            display_identity = self.message.sender_profile.group_name_card or self.message.sender_profile.nickname or self.message.sender_profile.qq_num
        else:
            display_identity = self.message.sender_num

        txt_path = output_path / f"{file_name}.txt"
        content_str = f"""{self.readable_time} {display_identity}\n"""

        for content in self.contents:
            content_str += f"{content[0]}\n{content[1]}\n"

        content_str += "\n"

        group_manager.add(txt_path, content_str)
