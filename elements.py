from ast import literal_eval
from json import loads
from xml.etree.ElementTree import fromstring


class Text:
    def __init__(self, element):
        self.text = element.text

        self.content = self._get_content()

    def _get_content(self):
        return "[文本]", self.text


class Image:
    def __init__(self, element):
        self.text = element.imageText
        self.file_name = element.fileName
        self.file_path = element.imageFilePath
        self.file_url = element.imageUrlOrigin

        self.content = self._get_content()

    def _get_content(self):
        return "[图片]", f"{self.text}-{self.file_name}{"\n" + self.file_path}{"\n" + self.file_url}"


class File:
    def __init__(self, element):
        self.file_name = element.fileName

        self.content = self._get_content()

    def _get_content(self):
        return "[文件]", self.file_name


class Emoji:
    def __init__(self, element):
        self.emoji_id = element.emojiId
        self.text = element.emojiText

        self.content = self._get_content()

    def _get_content(self):
        return "[表情]", f"{self.text}-{self.emoji_id}"


class Notice:
    def __init__(self, element):
        self.info = element.noticeInfo
        self.info2 = element.noticeInfo2

        self.content = self._get_content()

    def _get_content(self):
        if not self.info and not self.info2:
            return "[提示]", None
        elif self.info:
            root = fromstring(self.info)
            texts = [
                elem.get('txt')
                for elem in root.findall('.//nor')
                if elem.get('txt')
            ]
        elif self.info2:
            info2_dict = literal_eval(self.info2.replace(r"\/", "/"))
            texts = [item.get("txt", "")
                     for item
                     in info2_dict["items"]]

        return "[提示]", " ".join(texts)


class Application:
    def __init__(self, element):
        self.raw = element.applicationMessage

        self.content = self._get_content()

    def _get_content(self):
        return "[应用消息]", loads(self.raw)["prompt"]


class Call:
    def __init__(self, element):
        self.status = element.callStatus
        self.text = element.callText

        self.content = self._get_content()

    def _get_content(self):
        return "[通话]", f"{self.status}-{self.text}"


class Feed:
    def __init__(self, element):
        self.title = element.feedTitle.text
        self.feed_content = element.feedContent.text
        self.url = element.feedUrl

        self.content = self._get_content()

    def _get_content(self):
        return "[动态消息]", f"{self.title}\n{self.feed_content}\n{self.url}"
