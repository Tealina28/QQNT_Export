from json import loads

from exporter.base_elements import *

__all__ = ["Text",
           "Image",
           "File",
           "Voice",
           "Video",
           "Emoji",
           "Notice",
           "RedPacket",
           "Application",
           "Call",
           "Feed"]

class Text(BaseText):
    def _get_content(self):
        return self.text

class Image(BaseImage):
    def _get_content(self):

        return f"""<img src="{self.cache_path}" alt={self.text} {self.readable_size}" />"""

class File(BaseFile):
    def _get_content(self):
        return f"[文件] {self.file_name} {self.readable_size}"

class Voice(BaseVoice):
    def _get_content(self):
        return f"[语音]" + " ".join(
            part for part in [
                f"{self.voice_len}″ {self.voice_text}",
                self.file_name,
                self.readable_size
            ] if part
        )

class Video(BaseVideo):
    def _get_content(self):
        return "[视频]" + " ".join(
            part for part in [
                f"{self.formated_video_len} {self.file_name} {self.readable_size}",
                self.path
            ] if part
        )

class Emoji(BaseEmoji):
    def _get_content(self):
        return f"[表情]{self.text}-{self.emoji_id}"

class Notice(BaseNotice):
    def _get_content(self):
        return f"[提示]{self._parse_info()}"

class RedPacket(BaseRedPacket):
    def _get_content(self):
        return f"[红包]{self.summary} {self.prompt}"

class Application(BaseApplication):
    def _get_content(self):
        return f"[应用消息]{loads(self.raw)["prompt"]}"

class Call(BaseCall):
    def _get_content(self):
        return f"[通话]{self.status}-{self.text}"

class Feed(BaseFeed):
    def _get_content(self):
        return f"[动态消息]{self.title} <br /> {self.feed_content} <br /> <img src={self.url} alt= {self.feed_content} />"
