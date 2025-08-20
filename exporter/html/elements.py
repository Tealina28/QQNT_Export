from json import loads, JSONDecodeError

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

        return f"""<img src="file:///{self.cache_path}" alt="{self.text} {self.readable_size}" />"""

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
        if self.raw and self.raw.strip():
            try:
                data = loads(self.raw)
                prompt = data.get("prompt", "（无提示信息）") # 使用 .get() 避免因缺少 "prompt" 键而引发 KeyError
                return f"[应用消息]{prompt}"
            except JSONDecodeError:
                # 如果 self.raw 不是有效的 JSON，可以在这里处理
                return "[应用消息]（无效的消息格式）"
        return "[应用消息]（空消息）"

class Call(BaseCall):
    def _get_content(self):
        return f"[通话]{self.status}-{self.text}"

class Feed(BaseFeed):
    def _get_content(self):
        return f"""[动态消息]{self.title} <br /> {self.feed_content} <br /> <img src="{self.url}"/>"""
