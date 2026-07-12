"""
消息解析器

将数据库中的消息对象转换为统一的 ParsedMessage 对象。
"""

from collections.abc import Iterable
from typing import Optional
import logging

import element_pb2

from db import DatabaseManager
from db.models import (
    C2cMessage,
    DatalineMessage,
    GroupMessage,
    ProfileInfo,
    GroupMember,
)
from .dataline import (
    DATALINE_PAD_UID,
    DATALINE_PC_UID,
    DATALINE_PHONE_UID,
    dataline_device_name,
)
from .models import (
    ElementType,
    ParsedElement,
    ParsedMember,
    ParsedMessage,
    ParsedReaction,
)
from .elements import ElementParser, _parse_forward_cache, _quote_reference


logger = logging.getLogger(__name__)


class MessageParser:
    """消息解析器"""

    def __init__(self, dbman: DatabaseManager):
        """初始化解析器

        Args:
            dbman: 数据库管理器
        """
        self.dbman = dbman
        # “我”（当前登录账号）的成员信息缓存
        self._self_member: Optional[ParsedMember] = None
        self._self_member_resolved = False

    def parse_c2c_message(self, msg: C2cMessage) -> ParsedMessage:
        """解析私聊消息

        Args:
            msg: C2cMessage 对象

        Returns:
            ParsedMessage 对象
        """
        elements, cached_messages = self._parse_elements(msg)
        quoted_msg_id, quoted_msg_seq = self._resolve_quote_reference(
            msg, elements, cached_messages
        )

        return ParsedMessage(
            msg_id=str(msg.id),
            seq=msg.seq,
            sender_uid=msg.sender_uid,
            sender_num=msg.sender_num,
            timestamp=msg.time,
            elements=elements,
            quoted_msg_id=quoted_msg_id,
            quoted_msg_seq=quoted_msg_seq,
            reactions=self._parse_reactions(msg),
        )

    def parse_dataline_message(self, msg: DatalineMessage) -> ParsedMessage:
        """按私聊结构解析数据线消息。"""
        return self.parse_c2c_message(msg)

    def parse_group_message(self, msg: GroupMessage) -> ParsedMessage:
        """解析群聊消息

        Args:
            msg: GroupMessage 对象

        Returns:
            ParsedMessage 对象
        """
        elements, cached_messages = self._parse_elements(msg)
        quoted_msg_id, quoted_msg_seq = self._resolve_quote_reference(
            msg, elements, cached_messages
        )

        return ParsedMessage(
            msg_id=str(msg.id),
            seq=msg.seq,
            sender_uid=msg.sender_uid,
            sender_num=msg.sender_num,
            timestamp=msg.time,
            elements=elements,
            quoted_msg_id=quoted_msg_id,
            quoted_msg_seq=quoted_msg_seq,
            reactions=self._parse_reactions(msg),
            # 群聊特有字段
            group_num=msg.mixed_group_num,
            sender_nickname=msg.nickname,
            sender_card=msg.group_name_card,
        )

    def _parse_elements(
        self,
        msg,
    ) -> tuple[list[ParsedElement], list[ParsedMessage]]:
        """解析消息中的所有元素

        Args:
            msg: C2cMessage 或 GroupMessage 对象

        Returns:
            (ParsedElement 列表, 40900 缓存消息列表)
        """
        cached_messages = []
        cache_bytes = getattr(msg, 'UNK_18', None)
        if getattr(msg, 'msg_type', None) in (8, 9) and cache_bytes:
            cached_messages = _parse_forward_cache(cache_bytes)

        raw_elements = msg.elements
        elements = [
            ElementParser.parse(element, cached_messages)
            for element in raw_elements.elements
        ]
        recovery = getattr(msg, '_message_body_recovery', None)
        if recovery:
            elements.append(ParsedElement(
                type=ElementType.OTHER,
                content={
                    'raw_type': 0,
                    'raw_hex': recovery['raw_hex'],
                    'parse_error': recovery['parse_error'],
                    'dropped_fields': recovery['dropped_fields'],
                    'recovered_message_body': True,
                },
            ))
        return elements, cached_messages

    @staticmethod
    def _resolve_quote_reference(
        msg,
        elements: list[ParsedElement],
        cached_messages: list[ParsedMessage],
    ) -> tuple[Optional[str], Optional[int]]:
        """优先使用引用元素的原消息 ID，再回退到 40900 缓存。"""
        quoted_msg_id, quoted_msg_seq = _quote_reference(elements)

        if getattr(msg, 'msg_type', None) == 9 and cached_messages:
            cached = cached_messages[0]
            quoted_msg_id = quoted_msg_id or cached.msg_id
            quoted_msg_seq = quoted_msg_seq or cached.seq

        if not quoted_msg_seq:
            quoted_msg_seq = getattr(msg, 'quoted_seq', None) or None

        return quoted_msg_id, quoted_msg_seq

    @staticmethod
    def _parse_reactions(msg) -> list[ParsedReaction]:
        """解析消息列 40062 中的群贴表情。"""
        blob = getattr(msg, 'reactions_body', None)
        if not blob:
            return []

        reactions = element_pb2.EmojiStickers()
        try:
            reactions.ParseFromString(blob)
        except Exception as exc:
            logger.warning(
                "failed to decode message reactions: msg_id=%s error=%s",
                getattr(msg, 'id', ''),
                exc,
            )
            return []

        return [
            ParsedReaction(
                emoji_id=reaction.emojiId,
                count=reaction.count,
                is_self=reaction.isSelf,
                set_flag=reaction.setFlag,
            )
            for reaction in reactions.stickers
        ]

    def get_c2c_member(self, uid: str) -> Optional[ParsedMember]:
        """获取私聊对象的成员信息

        Args:
            uid: 对方的 UID

        Returns:
            ParsedMember 对象，如果找不到返回 None
        """
        profile = self.dbman.profile_info(uid)
        if not profile:
            return None

        return ParsedMember(
            platform_id=profile.uid,
            qq_num=profile.qq_num,
            nickname=profile.nickname or "",
            remark=profile.remark,
        )

    def get_self_member(self) -> Optional[ParsedMember]:
        """识别并返回“我”（当前登录账号）的成员信息。

        nt_msg.db 的 uid 映射表首项即本账号，直接取其 uid 与 qq 号；
        昵称尽量用好友资料补全（该表通常不含自己），缺失时回退为 qq 号。
        结果缓存，避免重复查询。
        """
        if self._self_member_resolved:
            return self._self_member
        self._self_member_resolved = True

        mapping = self.dbman.self_uid_mapping()
        if not mapping or not mapping.uid:
            return None

        nickname = ""
        remark = None
        profile = self.dbman.profile_info(mapping.uid)
        if profile:
            nickname = profile.nickname or ""
            remark = profile.remark

        self._self_member = ParsedMember(
            platform_id=mapping.uid,
            qq_num=mapping.qq_num,
            nickname=nickname or str(mapping.qq_num),
            remark=remark,
        )
        return self._self_member

    def get_dataline_members(
        self,
        messages: Iterable[ParsedMessage],
        owner_id: str = DATALINE_PC_UID,
    ) -> list[ParsedMember]:
        """构建数据线设备成员，并确保配置的 ownerId 在成员列表中。"""
        mapping = self.dbman.self_uid_mapping() if self.dbman else None
        qq_num = mapping.qq_num if mapping else 0
        uids = set()
        for msg in messages:
            if not qq_num and msg.sender_num:
                qq_num = msg.sender_num
            if msg.sender_uid:
                uids.add(msg.sender_uid)
        uids.add(owner_id)
        order = {
            DATALINE_PC_UID: 1,
            DATALINE_PHONE_UID: 2,
            DATALINE_PAD_UID: 3,
        }
        order[owner_id] = 0
        return [
            ParsedMember(
                platform_id=uid,
                qq_num=qq_num,
                nickname=dataline_device_name(uid),
            )
            for uid in sorted(uids, key=lambda uid: (order.get(uid, 99), uid))
        ]

    def get_group_member(self, group_num: int, uid: str) -> Optional[ParsedMember]:
        """获取群成员信息

        Args:
            group_num: 群号
            uid: 成员 UID

        Returns:
            ParsedMember 对象，如果找不到返回 None
        """
        from db.models import GroupMember

        member = (
            self.dbman.session.query(GroupMember)
            .filter(GroupMember.group_number == group_num)
            .filter(GroupMember.uid == uid)
            .first()
        )

        return self._parse_group_member(member)

    @staticmethod
    def _parse_group_member(member) -> Optional[ParsedMember]:
        """将群成员 ORM 转为统一模型，忽略 QQNT 的空占位行。"""
        if not member or not member.uid:
            return None

        return ParsedMember(
            platform_id=member.uid,
            qq_num=member.qq_num,
            nickname=member.nickname or "",
            group_nickname=member.group_name_card,
            is_owner=member.manager_flag == 2,
            is_admin=member.manager_flag == 1,
        )

    def get_all_group_members(self, group_num: int) -> list[ParsedMember]:
        """获取群所有成员信息

        Args:
            group_num: 群号

        Returns:
            ParsedMember 列表
        """
        from db.models import GroupMember

        members = (
            self.dbman.session.query(GroupMember)
            .filter(GroupMember.group_number == group_num)
            .filter(GroupMember.uid.is_not(None))
            .filter(GroupMember.uid != '')
            .all()
        )

        result = []
        for member in members:
            parsed = self._parse_group_member(member)
            if parsed:
                result.append(parsed)

        return result
