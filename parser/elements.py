"""
Element 解析器

使用注册机制将 protobuf element 转换为 ParsedElement，易于扩展新的元素类型。
"""

from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from .models import ParsedElement, ElementType


class ElementParser:
    """Element 解析器注册中心"""

    _parsers: dict[int, Callable] = {}

    @classmethod
    def register(cls, type_id: int):
        """注册解析器装饰器

        Args:
            type_id: protobuf element.type 的值

        Example:
            @ElementParser.register(1)
            def parse_text(element):
                return ParsedElement(...)
        """
        def decorator(func: Callable):
            cls._parsers[type_id] = func
            return func
        return decorator

    @classmethod
    def parse(cls, element) -> Optional[ParsedElement]:
        """解析单个 element

        Args:
            element: protobuf Element 对象

        Returns:
            ParsedElement 对象，未知类型返回 None
        """
        parser = cls._parsers.get(element.type)
        if parser:
            return parser(element)

        # 未知类型返回 OTHER
        return ParsedElement(
            type=ElementType.OTHER,
            content={'raw_type': element.type}
        )


# ============================================================================
# Element 解析器实现（使用装饰器注册）
# ============================================================================

@ElementParser.register(1)
def parse_text(element) -> ParsedElement:
    """解析文本消息"""
    return ParsedElement(
        type=ElementType.TEXT,
        content={
            'text': element.text
        }
    )


@ElementParser.register(2)
def parse_image(element) -> ParsedElement:
    """解析图片消息"""
    content = {
        'filename': element.fileName,
        'size': element.fileSize,
        'text': element.imageText,  # 图片描述文字
        'file_path': element.imageFilePath,
        'url_origin': element.imageUrlOrigin,
    }

    # MD5（用于计算缓存路径）
    if element.md5HexStr:
        content['md5'] = element.md5HexStr.hex().upper()
        content['original'] = element.original  # 0=非原图, 1=原图

    return ParsedElement(
        type=ElementType.IMAGE,
        content=content
    )


@ElementParser.register(3)
def parse_file(element) -> ParsedElement:
    """解析文件消息"""
    return ParsedElement(
        type=ElementType.FILE,
        content={
            'filename': element.fileName,
            'size': element.fileSize,
        }
    )


@ElementParser.register(4)
def parse_voice(element) -> ParsedElement:
    """解析语音消息"""
    return ParsedElement(
        type=ElementType.VOICE,
        content={
            'filename': element.fileName,
            'size': element.fileSize,
            'duration': element.voiceLen,  # 秒
            'text': element.voiceText,  # 语音转文字
        }
    )


@ElementParser.register(5)
def parse_video(element) -> ParsedElement:
    """解析视频消息"""
    return ParsedElement(
        type=ElementType.VIDEO,
        content={
            'filename': element.fileName,
            'size': element.fileSize,
            'duration': element.videoLen,  # 秒
            'path': element.videoPath,
            'width': element.videoWidth,
            'height': element.videoHeight,
        }
    )


@ElementParser.register(6)
def parse_emoji(element) -> ParsedElement:
    """解析表情消息"""
    # 尝试从 emojis.py 获取表情名称
    from emojis import emojis

    emoji_text = element.emojiText
    if not emoji_text and element.emojiId:
        emoji_text = emojis.get(element.emojiId, f"[表情:{element.emojiId}]")

    return ParsedElement(
        type=ElementType.EMOJI,
        content={
            'emoji_id': element.emojiId,
            'text': emoji_text,
            'raw_text': element.emojiText,  # 原始外显文字（未经查表回退）
        }
    )


@ElementParser.register(7)
def parse_quote(element) -> ParsedElement:
    """解析引用消息（递归解析被引用的内容）"""
    quoted_content = None
    if element.quotedElement and element.quotedElement.type:
        quoted_elem = ElementParser.parse(element.quotedElement)
        if quoted_elem:
            quoted_content = quoted_elem.content

    return ParsedElement(
        type=ElementType.QUOTE,
        content={
            'sender_uid': element.senderUid,
            'sender_num': element.senderNum,
            'quoted_timestamp': element.quotedTimestamp,
            'quoted_content': quoted_content,
        }
    )


@ElementParser.register(8)
def parse_notice(element) -> ParsedElement:
    """解析系统提示消息"""
    from unicodedata import category
    from lxml import etree as lxml_etree
    from ast import literal_eval

    notice_text = ""

    if element.noticeInfo:
        # 清理字符串
        info = element.noticeInfo.replace(r'\/', '/').replace('　', ' ')
        info = ''.join(char for char in info if category(char) not in ('Cf', 'Cc'))

        try:
            recover_parser = lxml_etree.XMLParser(recover=True)
            try:
                root = lxml_etree.fromstring(info)
            except lxml_etree.XMLSyntaxError:
                root = lxml_etree.fromstring(info.encode("utf-8"), parser=recover_parser)

            texts = [elem.get('txt') for elem in root.findall('.//nor') if elem.get('txt')]
            notice_text = " ".join(texts)
        except Exception:
            notice_text = element.noticeInfo

    elif element.noticeInfo2:
        try:
            info2_dict = literal_eval(element.noticeInfo2.replace(r"\/", "/"))
            texts = [item.get("txt", "") for item in info2_dict.get("items", [])]
            notice_text = " ".join(texts)
        except Exception:
            notice_text = element.noticeInfo2

    return ParsedElement(
        type=ElementType.NOTICE,
        content={
            'text': notice_text or "[系统提示]",
            'raw': element.noticeInfo or element.noticeInfo2,  # 原始 XML/字典字符串
        }
    )


@ElementParser.register(9)
def parse_red_packet(element) -> ParsedElement:
    """解析红包消息"""
    return ParsedElement(
        type=ElementType.RED_PACKET,
        content={
            'prompt': element.redPacket.prompt,
            'summary': element.redPacket.summary,
            'greeting': element.redPacket.greeting if hasattr(element.redPacket, 'greeting') else None,
        }
    )


@ElementParser.register(10)
def parse_application(element) -> ParsedElement:
    """解析应用消息（小程序、分享卡片等）"""
    return ParsedElement(
        type=ElementType.APPLICATION,
        content={
            'raw': element.applicationMessage,
        }
    )


@ElementParser.register(11)
def parse_market_face(element) -> ParsedElement:
    """解析商城表情（原创表情）"""
    return ParsedElement(
        type=ElementType.MARKET_FACE,
        content={
            'text': element.marketFaceText,  # 外显文本，如 "[贴贴]"
            'package_id': element.marketFacePackageId,
            'key': element.marketFaceKey,
        }
    )


@ElementParser.register(14)
def parse_markdown(element) -> ParsedElement:
    """解析 markdown 消息（常见于机器人）"""
    return ParsedElement(
        type=ElementType.MARKDOWN,
        content={
            'text': element.markdownText,
        }
    )


@ElementParser.register(16)
def parse_xml(element) -> ParsedElement:
    """解析 XML 消息"""
    return ParsedElement(
        type=ElementType.XML,
        content={
            'xml': element.xmlContent,
        }
    )


@ElementParser.register(21)
def parse_call(element) -> ParsedElement:
    """解析通话消息"""
    return ParsedElement(
        type=ElementType.CALL,
        content={
            'status': element.callStatus,
            'text': element.callText,
        }
    )


@ElementParser.register(27)
def parse_bubble_face(element) -> ParsedElement:
    """解析弹射/平底锅表情"""
    return ParsedElement(
        type=ElementType.BUBBLE_FACE,
        content={
            'summary': element.bubbleFaceSummary,  # 外显摘要，如 "[平底锅]x10"
            'emoji_id': element.emojiId,
            'emoji_text': element.emojiText,
        }
    )


@ElementParser.register(28)
def parse_location(element) -> ParsedElement:
    """解析位置共享消息"""
    return ParsedElement(
        type=ElementType.LOCATION,
        content={
            'text': element.locationText,
        }
    )


@ElementParser.register(44)
def parse_bot_chat(element) -> ParsedElement:
    """解析机器人对话消息"""
    return ParsedElement(
        type=ElementType.BOT,
        content={
            'text': element.markdownText,
        }
    )


@ElementParser.register(26)
def parse_feed(element) -> ParsedElement:
    """解析动态消息"""
    return ParsedElement(
        type=ElementType.FEED,
        content={
            'title': element.feedTitle.text if element.feedTitle else None,
            'content': element.feedContent.text if element.feedContent else None,
            'url': element.feedUrl,
        }
    )


# ============================================================================
# 辅助函数
# ============================================================================

@lru_cache(maxsize=4096)
def compute_image_cache_path(md5: str, original: int, pic_path: Optional[Path]) -> Optional[Path]:
    """计算图片缓存路径（仿照 QQ 的 CRC64 算法）

    Args:
        md5: 图片 MD5（大写十六进制）
        original: 0=非原图(chatraw), 1=原图(chatimg)
        pic_path: chatpic 根目录

    Returns:
        完整的缓存路径，如果 pic_path 为 None 则返回 None
    """
    if not pic_path:
        return None

    def crc64(raw_str: str) -> int:
        """CRC64 校验"""
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

    folder = "chatimg" if original else "chatraw"
    raw_str = f"{folder}:{md5}"
    crc64_value = crc64(raw_str)
    file_name = f"Cache_{crc64_value:x}"

    return pic_path / folder / file_name[-3:] / file_name
