"""
Element 解析器

使用注册机制将 protobuf element 转换为 ParsedElement，易于扩展新的元素类型。
"""

from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional
import logging

from google.protobuf.message import DecodeError

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
    def parse(
        cls,
        element,
        forward_messages: Optional[list[ParsedMessage]] = None,
    ) -> ParsedElement:
        """解析单个 element

        Args:
            element: protobuf Element 对象
            forward_messages: 已解析的 40900 子消息（用于合并转发元素）

        Returns:
            ParsedElement 对象。未知或解析失败的类型返回 OTHER，
            并保留原始 protobuf 数据。
        """
        parser = cls._parsers.get(element.type)
        if not parser:
            return _other_element(element)

        try:
            if element.type in (10, 16):
                return parser(element, forward_messages)
            return parser(element)
        except Exception as exc:
            logger.exception(
                "failed to parse element: type=%s id=%s",
                element.type,
                getattr(element, 'id', 0),
            )
            return _other_element(element, str(exc))


def _other_element(element, error: Optional[str] = None) -> ParsedElement:
    """保留未知或失败元素的原始数据，便于后续反向分析。"""
    content = {
        'raw_type': getattr(element, 'type', 0),
        'raw_hex': element.SerializeToString().hex(),
    }
    if error:
        content['parse_error'] = error
    return ParsedElement(type=ElementType.OTHER, content=content)


# ============================================================================
# Element 解析器实现（使用装饰器注册）
# ============================================================================

@ElementParser.register(1)
def parse_text(element) -> ParsedElement:
    """解析文本消息"""
    return ParsedElement(
        type=ElementType.TEXT,
        content={
            'text': element.text,
            'is_at': bool(element.bubbleId or element.atMentionMask),
            'bubble_id': element.bubbleId or None,
            'at_mention_mask': element.atMentionMask or None,
        }
    )


@ElementParser.register(2)
def parse_image(element) -> ParsedElement:
    """解析图片消息"""
    summary = '\n'.join(element.mediaSummary)
    content = {
        'filename': element.fileName,
        'size': element.fileSize,
        'text': summary,
        'file_path': element.imageFilePath or element.filePath,
        'width': element.mediaWidth,
        'height': element.mediaHeight,
        'image_type': element.imageType,
        'url_origin': element.imageUrlOrigin,
        'url_preview': element.imageUrlHigh,
        'url_thumbnail': element.imageUrlLow,
        'file_token': element.fileToken,
        'upload_time': element.uploadTime,
        'upload_timestamp': element.uploadTimestamp,
        'file_ttl': element.fileTTL,
        'cdn_host': element.cdnHost,
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
            'file_path': element.filePath,
            'file_token': element.fileToken,
            'transfer_flag': element.transferFlag,
            'md5': element.md5HexStr.hex() if element.md5HexStr else None,
            'content_hash': element.contentHash.hex() if element.contentHash else None,
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
            'file_path': element.filePath,
            'file_token': element.fileToken,
            'ptt_type': element.pttType,
            'voice_changed': element.voiceChanged,
            'waveform': element.waveform.hex() if element.waveform else None,
            'text': element.voiceText,
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
            'cover_width': element.mediaWidth,
            'cover_height': element.mediaHeight,
            'cover_filename': element.coverFileName,
            'file_token': element.fileToken,
            'video_token': element.videoToken,
            'expire_timestamp': element.expireTimestamp,
            'valid_period': element.validPeriodSec,
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
            'sub_type': element.subType,
            'extended_description': element.faceExtDesc or None,
            'super_category': element.superEmojiCategory or None,
            'animated_sticker_id': element.animatedStickerId or None,
            'dice_value': element.diceValue or None,
            'can_chain': element.canChain,
        }
    )


@ElementParser.register(7)
def parse_quote(element) -> ParsedElement:
    """解析引用消息（递归解析被引用的内容）"""
    quoted_elements = [
        ElementParser.parse(quoted_element)
        for quoted_element in element.origElements
    ]

    return ParsedElement(
        type=ElementType.QUOTE,
        content={
            'sender_uid': element.origSenderUid,
            'receiver_uid': element.origReceiverUid,
            'sender_num': element.origSenderNum,
            'receiver_num': element.origReceiverNum,
            'orig_msg_id': str(element.origMsgId) if element.origMsgId else None,
            'orig_msg_id_ref': (
                str(element.replyOrigMsgIdRef)
                if element.replyOrigMsgIdRef else None
            ),
            'orig_msg_seq': element.origMsgSeq or None,
            'orig_msg_index': element.origMsgIndex or None,
            'quoted_timestamp': element.origMsgTime,
            'quoted_elements': quoted_elements,
            'summary': element.replyTextSummary,
        }
    )


@ElementParser.register(8)
def parse_notice(element) -> ParsedElement:
    """解析撤回、戳一戳、入群/移除/解散、禁言和邀请等灰条。"""
    raw = element.noticeInfo or element.noticeInfo2
    content = {
        'text': _notice_text(element.noticeInfo, element.noticeInfo2),
        'raw': raw,
        'sub_type': element.subType,
        'notice_type': 'generic',
    }

    if element.subType == 1 or element.recallSenderUid or element.recallRevokeUid:
        recalled_elements = [
            ElementParser.parse(recalled)
            for recalled in element.recallElements
        ]
        content.update({
            'notice_type': 'withdraw',
            'sender_uid': element.recallSenderUid or None,
            'recaller_uid': element.recallRevokeUid or element.recallSenderUid or None,
            'sender_name': element.recallSenderName or None,
            'recaller_name': element.recallRevokeName or element.recallSenderName or None,
            'display_text': element.recallDisplayText or None,
            'recalled_elements': recalled_elements,
        })
    elif element.subType == 4 or element.groupTipType:
        event_names = {1: 'join', 2: 'dismiss', 3: 'remove'}
        mute_info = None
        if element.HasField('muteInfo'):
            mute_info = {
                'operator_uid': element.muteInfo.operator.uid or None,
                'target_uid': element.muteInfo.mutedUser.uid or None,
                'target_name': element.muteInfo.mutedUser.groupNickname or None,
                'timestamp': element.muteInfo.timestamp or None,
                'duration': element.muteInfo.duration,
            }
        content.update({
            'notice_type': 'group',
            'group_event': event_names.get(element.groupTipType, 'generic'),
            'group_tip_type': element.groupTipType,
            'user1_uid': element.groupTipUser1Uid or None,
            'user1_name': element.groupTipUser1Card or element.groupTipUser1Name or None,
            'user2_uid': element.groupTipUser2Uid or None,
            'user2_name': element.groupTipUser2Card or element.groupTipUser2Name or None,
            'mute_info': mute_info,
        })
    elif element.subType in (12, 17) or element.actionId:
        notice_type = 'action'
        if element.actionId == 12 or element.actionDetailId == 1061 or '戳' in content['text']:
            notice_type = 'interactive'
        elif '邀请' in content['text']:
            notice_type = 'invite'
        elif element.actionId == 16 or '红包' in content['text']:
            notice_type = 'wallet'
        content.update({
            'notice_type': notice_type,
            'actor_uid': element.actionInitiator.uid or None,
            'actor_name': element.actionInitiator.nickname or None,
            'target_uid': element.actionTarget.uid or None,
            'target_name': element.actionTarget.nickname or None,
            'action_id': element.actionId,
            'action_detail_id': element.actionDetailId,
            'business_id': element.actionBusinessId,
            'action_unique_id': element.actionUniqueId,
            'attributes': [
                {'key': attr.key, 'value': attr.value}
                for attr in element.actionAttributes
            ],
        })

    content['text'] = content['text'] or content.get('display_text') or "[系统提示]"
    return ParsedElement(type=ElementType.NOTICE, content=content)


def _notice_text(xml_text: str, json_text: str) -> str:
    """从灰条 XML/JSON 中尽可能提取可读文本。"""
    import json
    from unicodedata import category
    from lxml import etree as lxml_etree

    if xml_text:
        cleaned = xml_text.replace(r'\/', '/').replace('　', ' ')
        cleaned = ''.join(char for char in cleaned if category(char) not in ('Cf', 'Cc'))
        try:
            root = lxml_etree.fromstring(
                cleaned.encode('utf-8'),
                parser=lxml_etree.XMLParser(recover=True),
            )
            parts = []
            for node in root.iter():
                value = node.get('txt') or node.get('nm')
                if value:
                    parts.append(value)
            return ' '.join(parts)
        except Exception:
            return cleaned

    if json_text:
        try:
            payload = json.loads(json_text.replace(r'\/', '/'))
            return ' '.join(
                item.get('txt') or item.get('nm') or ''
                for item in payload.get('items', [])
            ).strip()
        except Exception:
            return json_text
    return ''


@ElementParser.register(9)
def parse_red_packet(element) -> ParsedElement:
    """解析红包和转账消息。"""
    detail = element.walletDetail
    wallet_type = element.walletRedbagType or detail.redbagType
    return ParsedElement(
        type=ElementType.RED_PACKET,
        content={
            'wallet_type': 'transfer' if wallet_type == 1 else 'red_packet',
            'redbag_type': wallet_type,
            'target_num': element.walletTargetNum or None,
            'order_id': element.walletOrderId or None,
            'prompt': detail.prompt,
            'summary': detail.display,
            'greeting': detail.title,
            'subtitle': detail.subtitle,
            'cover': element.walletExt.cover or None,
        }
    )


@ElementParser.register(10)
def parse_application(
    element,
    forward_messages: Optional[list[ParsedMessage]] = None,
) -> ParsedElement:
    """解析应用消息（小程序、分享卡片等）

    Args:
        element: protobuf Element 对象
        forward_messages: 已解析的 40900 子消息（兼容旧版 Ark 转发卡片）
    """
    content = {
        'raw': element.applicationMessage,
    }

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
            'market_type': element.marketFaceType,
            'preview_md5': (
                element.marketFacePreviewMd5.hex()
                if element.marketFacePreviewMd5 else None
            ),
            'preview_width': element.marketFacePreviewWidth,
            'preview_height': element.marketFacePreviewHeight,
            'media_type': element.marketFaceMediaType,
            'animated': element.marketFaceAnimated,
        }
    )


@ElementParser.register(14)
def parse_markdown(element) -> ParsedElement:
    """解析 markdown 消息（常见于机器人）"""
    flash_transfer = None
    if element.HasField('flashTransferInfo'):
        info = element.flashTransferInfo
        flash_transfer = {
            'file_set_id': info.fileSetId,
            'thumbnail_name': info.thumbnailName,
            'file_size': info.fileBytes,
            'thumbnail_file_id': info.thumbnail.fileId,
            'thumbnail_url': info.thumbnail.urlInfo.url,
            'create_time': info.createTime,
        }
    return ParsedElement(
        type=ElementType.MARKDOWN,
        content={
            'text': element.markdownText,
            'summary': element.markdownSummary,
            'flash_transfer': flash_transfer,
        }
    )


@ElementParser.register(16)
def parse_multi_msg(
    element,
    forward_messages: Optional[list[ParsedMessage]] = None,
) -> ParsedElement:
    """解析合并转发卡片及其 40900 子消息。"""
    content = {
        'res_id': element.multiMsgResId,
        'xml': element.xmlContent,
        'session_id': element.multiMsgSessionId,
    }
    if forward_messages:
        content['forward_messages'] = forward_messages
    return ParsedElement(
        type=ElementType.MULTI_MSG,
        content=content,
    )


@ElementParser.register(17)
def parse_markdown_buttons(element) -> ParsedElement:
    """解析 QQ Bot Markdown 按钮组。"""
    rows = []
    for row in element.markdownButtonRows:
        rows.append([
            {
                'id': button.id,
                'label': button.label or button.visitedLabel,
                'visited_label': button.visitedLabel or None,
                'style': button.style,
                'action_type': button.actionType,
                'action': button.action or None,
                'data': button.data or None,
                'permission_type': button.permissionType,
            }
            for button in row.buttons
        ])
    return ParsedElement(
        type=ElementType.MARKDOWN_BUTTON,
        content={
            'app_id': element.markdownButtonAppId,
            'rows': rows,
        },
    )


@ElementParser.register(21)
def parse_call(element) -> ParsedElement:
    """解析通话消息"""
    return ParsedElement(
        type=ElementType.CALL,
        content={
            'status': element.callStatus,
            'text': ' '.join(element.callSummary),
            'answer_type': element.callAnswerType,
            'duration_ms': element.callDurationMs,
            'method': element.callMethod,
        }
    )


@ElementParser.register(23)
def parse_online_file(element) -> ParsedElement:
    """解析在线文件。"""
    return ParsedElement(
        type=ElementType.ONLINE_FILE,
        content=_online_file_content(element),
    )


@ElementParser.register(27)
def parse_bubble_face(element) -> ParsedElement:
    """解析弹射/平底锅表情"""
    return ParsedElement(
        type=ElementType.BUBBLE_FACE,
        content={
            'summary': element.bubbleFaceSummary,  # 外显摘要，如 "[平底锅]x10"
            'emoji_id': element.bubbleFaceId,
            'emoji_text': element.bubbleFaceName or element.bubbleFacePcText,
            'pc_text': element.bubbleFacePcText,
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
            'dynamic_type': element.dynamicType,
            'dynamic_id': element.dynamicId,
            'title': element.dynamicDescription.main or None,
            'subtitle': element.dynamicDescription.sub or None,
            'content': element.dynamicDescription2.main or None,
            'content_subtitle': element.dynamicDescription2.sub or None,
            'cover_url': element.dynamicCoverUrl or None,
            'logo_url': element.dynamicLogoUrl or None,
            'publisher_num': element.dynamicPublisherNum or None,
            'metadata': element.dynamicMetadata or None,
            'tags': [tag.content for tag in element.dynamicTags if tag.content],
        }
    )


@ElementParser.register(30)
def parse_online_folder(element) -> ParsedElement:
    """解析在线文件夹。"""
    return ParsedElement(
        type=ElementType.ONLINE_FOLDER,
        content=_online_file_content(element),
    )


def _online_file_content(element) -> dict:
    return {
        'filename': element.fileName,
        'size': element.fileSize,
        'file_path': element.filePath,
        'file_token': element.fileToken,
        'transfer_flag': element.transferFlag,
        'width': element.mediaWidth,
        'height': element.mediaHeight,
    }


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

    cache = element_pb2.ForwardedMessages()
    try:
        cache.ParseFromString(cache_bytes)
    except DecodeError as exc:
        logger.warning("failed to decode 40900 message cache: %s", exc)
        return []

    return [_parse_forwarded_message(message) for message in cache.messages]


def _parse_forwarded_message(message) -> ParsedMessage:
    """递归转换一条 40900 消息缓存记录。"""
    nested_messages = [
        _parse_forwarded_message(sub_message)
        for sub_message in message.subMessages
    ]
    elements = [
        ElementParser.parse(element, nested_messages)
        for element in message.elements
    ]
    quoted_msg_id, quoted_msg_seq = _quote_reference(elements)

    return ParsedMessage(
        msg_id=str(message.msgId),
        seq=message.msgSeq,
        sender_uid=message.senderUid,
        sender_num=message.senderNum,
        timestamp=message.sendTime,
        elements=elements,
        quoted_msg_id=quoted_msg_id,
        quoted_msg_seq=quoted_msg_seq,
        sender_nickname=message.senderNickname or None,
    )


def _quote_reference(
    elements: list[ParsedElement],
) -> tuple[Optional[str], Optional[int]]:
    """从引用元素提取原消息雪花 ID 和序列号。"""
    for element in elements:
        if element.type != ElementType.QUOTE:
            continue
        msg_id = (
            element.content.get('orig_msg_id')
            or element.content.get('orig_msg_id_ref')
        )
        return msg_id, element.content.get('orig_msg_seq')
    return None, None


@lru_cache(maxsize=1)
def _qq_crc64_table() -> tuple[int, ...]:
    """构建 QQ 图片缓存路径使用的固定 CRC64 查表。"""
    table = [0] * 256
    for i in range(256):
        value = i
        for _ in range(8):
            value = (
                value >> 1 ^ -7661587058870466123
                if value & 1 else value >> 1
            )
        table[i] = value
    return tuple(table)


def _qq_crc64(raw_str: str) -> int:
    """计算 QQ 图片缓存路径使用的 CRC64。"""
    table = _qq_crc64_table()
    value = -1
    for char in raw_str:
        value = table[(ord(char) ^ value) & 255] ^ value >> 8
    return value


@lru_cache(maxsize=4096)
def compute_image_cache_paths(
    md5: str,
    original: int,
    pic_path: Optional[Path],
) -> tuple[Path, ...]:
    """计算图片在 chatpic 各缓存目录中的候选路径。

    Args:
        md5: 图片 MD5（大写十六进制）
        original: 图片元素的 original 字段，用于保持现有首选目录
        pic_path: chatpic 根目录

    Returns:
        按首选目录、另一图片目录、缩略图目录排列的候选路径
    """
    if not pic_path:
        return ()

    normalized_md5 = md5.upper()
    preferred = "chatimg" if original else "chatraw"
    folders = (preferred, "chatraw" if original else "chatimg", "chatthumb")
    paths = []
    for folder in folders:
        crc64_value = _qq_crc64(f"{folder}:{normalized_md5}")
        file_name = f"Cache_{crc64_value:x}"
        paths.append(pic_path / folder / file_name[-3:] / file_name)
    return tuple(paths)


@lru_cache(maxsize=4096)
def compute_image_cache_path(
    md5: str,
    original: int,
    pic_path: Optional[Path],
) -> Optional[Path]:
    """返回首个实际存在的图片缓存，并缓存本次运行的检查结果。"""
    candidates = compute_image_cache_paths(md5, original, pic_path)
    for path in candidates:
        if path.is_file():
            return path

    return None
