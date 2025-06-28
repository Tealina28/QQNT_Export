from atexit import register
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tqdm import tqdm

from .elements import *

from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader('.'))
template = env.get_template('template/template.html')

class HtmlExportManager:
    def __init__(self,dbman,queries, output_path, task_type):

        self.export_queue: dict[Path:list] = defaultdict(list)
        self.dbman = dbman
        self.queries = queries
        self.output_path = output_path
        self.task_type = task_type
        register(self.save)

    def process(self):
        Exporter = C2cHtmlExporter if self.task_type == "c2c" else GroupHtmlExporter
        for interlocutor_uid,query in self.queries.items():
            if self.task_type == "c2c":
                profile_info = self.dbman.profile_info(interlocutor_uid)
                if profile_info:
                    filename = profile_info.remark or profile_info.nickname
                elif query.first().mapping:
                    filename = query.first().mapping.qq_num
                else:
                    filename = query.first().interlocutor_num
            else:
                group_info = self.dbman.group_info(query.first().mixed_group_num)
                if group_info:
                    filename = group_info.remark or group_info.name
                else:
                    filename = query.first().mixed_group_num

            html_path = self.output_path / f"{filename}.html"
            for message in tqdm(query.all()):
                exporter = Exporter(message)
                self.export_queue[html_path].append(exporter.content_dict)

    def save(self):
        for path in self.export_queue:
            html_content = template.render(title = path.stem, messages = self.export_queue[path])
            with path.open(mode="w", encoding="utf-8") as f:
                f.write(html_content)

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
        self.content_dict = self._content_dict()

    def _extract(self):
        for element in self.message.elements.elements:
            self.contents.append(self._extract_single(element))

    def _extract_single(self, element):
        if element.type in self.elements_map:
            return self.elements_map[element.type](element).content
        elif element.type == 7:
            result = self._extract_single(element.quotedElement)
            if result:
                result = ("[被引用的消息]" + result)
            else:
                result = ("[被引用的消息]", result)
            return result

        return None

    def _content_dict(self):
        pass

class C2cHtmlExporter(BaseExporter):
    def __init__(self, message):
        super().__init__(message)


    def _content_dict(self):
        self._extract()

        if self.message.sender_flag == 0:
            display_identity = "收"
        elif self.message.sender_flag in (1, 2):
           display_identity = "发"
        elif self.message.sender_flag == 8:
            display_identity = "转发"
        else:
            display_identity = "未知"

        content_str = "\n"

        for content in self.contents:
            content_str += f"{content}\n"

        content_str += "\n"

        content_dict = {"readable_time": self.readable_time,
                        "display_identity": display_identity,
                        "content": content_str}

        return content_dict

class GroupHtmlExporter(BaseExporter):
    def __init__(self, message):
        super().__init__(message)

    def _content_dict(self):
        self._extract()

        if self.message.group_name_card:
            display_identity = self.message.group_name_card
        elif self.message.nickname:
            display_identity = self.message.nickname
        elif self.message.sender_profile:
            display_identity = self.message.sender_profile.group_name_card or self.message.sender_profile.nickname or self.message.sender_profile.qq_num
        else:
            display_identity = self.message.sender_num

        content_str = "\n"

        for content in self.contents:
            content_str += f"{content}\n"

        content_str += "\n"

        content_dict = {"readable_time": self.readable_time,
                        "display_identity": display_identity,
                        "content": content_str}

        return content_dict