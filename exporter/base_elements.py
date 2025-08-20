from ast import literal_eval
from functools import lru_cache
from xml.etree.ElementTree import fromstring, ParseError
from lxml import etree as lxml_etree

from humanize import naturalsize
from unicodedata import category

from emojis import emojis

pic_path = ""

__all__ = [
    "BaseText",
    "BaseImage",
    "BaseFile",
    "BaseVoice",
    "BaseVideo",
    "BaseEmoji",
    "BaseNotice",
    "BaseRedPacket",
    "BaseApplication",
    "BaseCall",
    "BaseFeed",
]


def readable_file_size(file_size):
    """
    Returns a human-readable file size.
    """
    return naturalsize(file_size, binary=True, format="%.2f") if file_size else None


class BaseText:
    def __init__(self, element):
        self.text = element.text

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseImage:
    def __init__(self, element):
        self.text = element.imageText
        self.file_name = element.fileName
        self.readable_size = readable_file_size(element.fileSize)
        self.file_path = element.imageFilePath
        self.file_url = element.imageUrlOrigin

        self.cache_path = self._get_cache_path(element.original, element.md5HexStr.hex().upper(),pic_path)

        self.content = self._get_content()

    @staticmethod
    @lru_cache(maxsize=4096)
    def _get_cache_path(original, md5HexStr, pic_path):
        def crc64(raw_str):
            _crc64_table = [0] * 256
            for i in range(256):
                bf = i
                for _ in range(8):
                    bf = bf >> 1 ^ -7661587058870466123 if bf & 1 else bf >> 1
                _crc64_table[i] = bf
            value = -1
            for char in raw_str:
                value = _crc64_table[(ord(char) ^ value) & 255] ^ value >> 8
            return value

        # original == 0 指未发原图，图片存于chatraw
        # original == 1 指发送原图，压缩后的图片存于chatimg,下载后原图存于chatraw
        folder = "chatimg" if original else "chatraw"
        raw_str = f"{folder}:{md5HexStr}"
        crc64_value = crc64(raw_str)
        file_name = f"Cache_{crc64_value:x}"

        return pic_path / folder/ file_name[-3:] / file_name

    def _get_content(self):
        pass


class BaseFile:
    def __init__(self, element):
        self.file_name = element.fileName
        self.readable_size = readable_file_size(element.fileSize)

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseVoice:
    def __init__(self, element):
        self.voice_text = element.voiceText
        self.voice_len = element.voiceLen
        self.file_name = element.fileName
        self.readable_size = readable_file_size(element.fileSize)

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseVideo:
    def __init__(self, element):
        self.formated_video_len = self._seconds_to_hms(element.videoLen)
        self.file_name = element.fileName
        self.readable_size = readable_file_size(element.fileSize)
        self.path = element.videoPath

        self.content = self._get_content()

    @staticmethod
    def _seconds_to_hms(seconds):
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def _get_content(self):
        pass


class BaseEmoji:
    def __init__(self, element):
        self.emoji_id = element.emojiId
        self.text = element.emojiText or emojis.get(self.emoji_id, "未知表情")

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseNotice:
    def __init__(self, element):
        self.info = element.noticeInfo
        self.info2 = element.noticeInfo2

        self.content = self._get_content()

    def _parse_info(self):
        if not self.info and not self.info2:
            return "[提示]", None
        elif self.info:
            self.info = self.info.replace(r'\/', '/').replace('\u3000', ' ')
            self.info = ''.join(char for char in self.info if category(char) not in ('Cf', 'Cc'))

            recover_parser = lxml_etree.XMLParser(recover=True)
            try:
                root = fromstring(self.info)
            except ParseError:
                # 尝试使用恢复模式重新解析
                root = lxml_etree.fromstring(self.info.encode("utf-8"), parser=recover_parser)
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

        return " ".join(texts)

    def _get_content(self):
        pass


class BaseRedPacket:
    def __init__(self, element):
        self.prompt = element.redPacket.prompt
        self.summary = element.redPacket.summary

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseApplication:
    def __init__(self, element):
        self.raw = element.applicationMessage

        self.content = self._get_content()

    def _get_content(self):
        pass


class BaseCall:
    def __init__(self, element):
        self.status = element.callStatus
        self.text = element.callText

        self.content = self._get_content()

    def _get_content(self):
        pass

class BaseFeed:
    def __init__(self, element):
        self.title = element.feedTitle.text
        self.feed_content = element.feedContent.text
        self.url = element.feedUrl

        self.content = self._get_content()

    def _get_content(self):
        pass
