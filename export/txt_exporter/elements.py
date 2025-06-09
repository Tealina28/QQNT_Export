from export.base_elements import *

from json import loads

__all__ = [
    "Text",
    "Image",
    "File",
    "Voice",
    "Video",
    "Emoji",
    "Notice",
    "RedPacket",
    "Application",
    "Call",
    "Feed",
]

class Text(BaseText):
    def _get_content(self):
        return "[文本]", self.text


class Image(BaseImage):
    def _get_content(self):
        return "[图片]", "\n".join(
            part for part in [
                f"{self.text}{self.cache_path} {self.readable_size}",
                self.file_path,
                self.file_url
            ] if part
        )


class File(BaseFile):
    def _get_content(self):
        return "[文件]", f"{self.file_name} {self.readable_size}"


class Voice(BaseVoice):
    def _get_content(self):
        return "[语音]", "\n".join(
            part for part in [
                f"{self.voice_len}″ {self.voice_text}",
                self.file_name,
                self.readable_size
            ] if part
        )


class Video(BaseVideo):
    def _get_content(self):
        return "[视频]", "\n".join(
            part for part in [
                f"{self.formated_video_len} {self.file_name} {self.readable_size}",
                self.path
            ] if part
        )


class Emoji(BaseEmoji):
    def _get_content(self):
        return "[表情]", f"{self.text}-{self.emoji_id}"


class Notice(BaseNotice):
    def _get_content(self):
        return "[提示]", self._parse_info()

class RedPacket(BaseRedPacket):
    def _get_content(self):
        return "[红包]", f"{self.summary} {self.prompt}"


class Application(BaseApplication):
    def _get_content(self):
        return "[应用消息]", loads(self.raw)["prompt"]


class Call(BaseCall):
    def _get_content(self):
        return "[通话]", f"{self.status}-{self.text}"


class Feed(BaseFeed):
    def _get_content(self):
        return "[动态消息]", "\n".join(
            part for part in [
                self.title,
                self.feed_content,
                self.url
            ] if part
        )
