"""
Element 解析器

使用注册机制将 protobuf element 转换为 ParsedElement，易于扩展新的元素类型。
"""

from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional
import logging

from .models import ParsedElement, ElementType, ParsedMessage
import element_pb2


logger = logging.getLogger(__name__)


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
    def parse(cls, element, forward_cache_bytes: Optional[bytes] = None) -> Optional[ParsedElement]:
        """解析单个 element

        Args:
            element: protobuf Element 对象
            forward_cache_bytes: 合并转发的 40900 缓存字段（仅用于 type=10）

        Returns:
            ParsedElement 对象，未知类型返回 OTHER
        """
        parser = cls._parsers.get(element.type)
        if parser:
            # type=10 需要额外传入 forward_cache_bytes
            if element.type == 10:
                return parser(element, forward_cache_bytes)
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
        'sub_type': element.subType,       # 子类型：7=特殊动画表情，1/2=普通动画/超级秀
        'is_flash': element.imageIsFlash,  # 1=闪照
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
            'summary': element.quotedSummary,  # 原消息文本摘要（降级兜底，原始字段 47413）
        }
    )


@ElementParser.register(8)
def parse_notice(element) -> ParsedElement:
    """解析系统提示消息

    type 8（grayTipElement）涵盖三种子情况，统一在 content['notice_type'] 中标注：
    - 'withdraw'：撤回提示（存在 recallerUid 字段）
    - 'interactive'：互动提示（拍一拍/戳一戳，XML 内含多个 <qq uin> + <nor txt>）
    - 'generic'：其他普通灰字提示

    解析层只抽取原始字段（uid、原文等），uid→显示名 的解析交给导出层。
    """
    from unicodedata import category
    from lxml import etree as lxml_etree
    from ast import literal_eval
    import re

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

    content = {
        'text': notice_text or "[系统提示]",
        'raw': element.noticeInfo or element.noticeInfo2,  # 原始 XML/字典字符串
        'notice_type': 'generic',
    }

    # 撤回提示：存在撤回者 UID
    if element.recallerUid:
        content['notice_type'] = 'withdraw'
        content['recaller_uid'] = element.recallerUid
        content['recaller_name'] = element.recallerName  # 后备名（不可靠）
        content['suffix'] = element.recallSuffix
    elif element.noticeInfo:
        # 互动提示（拍一拍/戳一戳）：XML 内含至少两个 <qq uin> 与 <nor txt>
        uids = re.findall(r'<qq uin="([^"]+)"', element.noticeInfo)
        nor_texts = re.findall(r'<nor txt="([^"]*)"', element.noticeInfo)
        if len(uids) >= 2 and nor_texts:
            content['notice_type'] = 'interactive'
            content['actor_uid'] = uids[0]
            content['target_uid'] = uids[1]
            content['verb'] = nor_texts[0]
            content['suffix'] = nor_texts[1] if len(nor_texts) > 1 else ''

    return ParsedElement(
        type=ElementType.NOTICE,
        content=content
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
def parse_application(element, forward_cache_bytes: Optional[bytes] = None) -> ParsedElement:
    """解析应用消息（小程序、分享卡片等）

    Args:
        element: protobuf Element 对象
        forward_cache_bytes: 合并转发的 40900 缓存字段（仅当 msg_type==8 时传入）
    """
    content = {
        'raw': element.applicationMessage,
    }

    # 尝试展开合并转发（仅当提供了 forward_cache_bytes 时）
    if forward_cache_bytes:
        forward_messages = _parse_forward_cache(forward_cache_bytes)
        if forward_messages:
            content['forward_messages'] = forward_messages

    return ParsedElement(
        type=ElementType.APPLICATION,
        content=content
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

def _parse_forward_cache(cache_bytes: bytes) -> list[ParsedMessage]:
    """解析合并转发的 40900 缓存字段

    Args:
        cache_bytes: 40900 字段的原始字节（protobuf repeated ForwardedMessage）

    Returns:
        解析后的子消息列表（ParsedMessage）
    """
    if not cache_bytes:
        return []

    forwarded_messages = []
    offset = 0

    # 40900 字段是 repeated，手动解析每条子消息（tag=40900, wire_type=2）
    while offset < len(cache_bytes):
        try:
            # 读取 varint tag
            tag, offset = _read_varint(cache_bytes, offset)
            field_num = tag >> 3
            wire_type = tag & 0x7

            if field_num != 40900 or wire_type != 2:  # 期望 tag=40900, wire_type=length-delimited
                logger.warning(f"unexpected tag in 40900: field={field_num}, wire={wire_type}")
                break

            # 读取 length
            length, offset = _read_varint(cache_bytes, offset)
            sub_msg_bytes = cache_bytes[offset:offset + length]
            offset += length

            # 解析子消息
            fwd_msg = element_pb2.ForwardedMessage()
            fwd_msg.ParseFromString(sub_msg_bytes)

            # 解析子消息的 messageBody（40800 字段）
            # 40800 是 Elements（repeated Element），与主消息解析逻辑一致
            elements_list = []
            if fwd_msg.messageBody:
                try:
                    # 解析为 Elements（标准结构）
                    els = element_pb2.Elements()
                    els.ParseFromString(fwd_msg.messageBody)
                    for e in els.elements:
                        parsed = ElementParser.parse(e)
                        if parsed:
                            elements_list.append(parsed)
                except Exception:
                    # 降级：尝试解析为单个 Element（旧版兼容）
                    try:
                        elem = element_pb2.Element()
                        elem.ParseFromString(fwd_msg.messageBody)
                        parsed = ElementParser.parse(elem)
                        if parsed:
                            elements_list.append(parsed)
                    except Exception as e:
                        logger.warning(f"failed to parse forwarded message body: {e}")

            # 构建 ParsedMessage（子消息）
            # 优先使用 timestampAlt，但需用 is not None 判断以支持值为 0 的情况
            parsed_msg = ParsedMessage(
                msg_id=str(fwd_msg.msgId),
                sender_uid=fwd_msg.senderUid,
                sender_num=fwd_msg.senderNum,
                timestamp=fwd_msg.timestampAlt if fwd_msg.timestampAlt is not None and fwd_msg.timestampAlt != 0 else fwd_msg.timestamp,
                elements=elements_list,
            )
            forwarded_messages.append(parsed_msg)

        except Exception as e:
            logger.warning(f"failed to parse forward cache at offset {offset}: {e}")
            break

    return forwarded_messages


def _read_varint(buf: bytes, offset: int) -> tuple[int, int]:
    """读取 protobuf varint，返回 (值, 新偏移量)"""
    result = 0
    shift = 0
    while True:
        if offset >= len(buf):
            raise ValueError("varint extends beyond buffer")
        byte = buf[offset]
        offset += 1
        result |= (byte & 0x7f) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, offset


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
