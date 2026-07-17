"""
消息解析器

将数据库中的消息对象转换为统一的 ParsedMessage 对象。
"""

from collections.abc import Iterable
from typing import Optional
import logging

import element_pb2
from sqlalchemy.exc import SQLAlchemyError
from emojis import configure_emojis

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
from .avatar import public_user_avatar_url
from .models import (
    ElementType,
    ParsedElement,
    ParsedMember,
    ParsedMessage,
    ParsedReaction,
    normalize_sender_id,
)
from .elements import ElementParser, _parse_forward_cache, _quote_reference


logger = logging.getLogger(__name__)
GROUP_MEMBER_QUERY_CHUNK_SIZE = 900
GROUP_SENDER_SCAN_BATCH_SIZE = 1000


class MessageParser:
    """消息解析器"""

    def __init__(self, dbman: DatabaseManager):
        """初始化解析器

        Args:
            dbman: 数据库管理器
        """
        self.dbman = dbman
        configure_emojis(dbman.system_emojis())
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
        raw_elements = msg.elements
        needs_cached_messages = (
            getattr(msg, 'msg_type', None) == 9
            or any(element.type in (10, 16) for element in raw_elements.elements)
        )

        cached_messages = []
        cache_bytes = getattr(msg, 'UNK_18', None)
        if needs_cached_messages and cache_bytes:
            cached_messages = _parse_forward_cache(cache_bytes)

        elements = [
            ElementParser.parse(element, cached_messages)
            for element in raw_elements.elements
        ]
        if getattr(msg, 'msg_type', None) == 9 and cached_messages:
            self._enrich_quote_elements(elements, cached_messages)
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
    def _enrich_quote_elements(
        elements: list[ParsedElement],
        cached_messages: list[ParsedMessage],
    ) -> None:
        """用 40900 中的完整消息补全引用里的真实媒体元素。"""
        media_types = {
            ElementType.IMAGE,
            ElementType.FILE,
            ElementType.VOICE,
            ElementType.VIDEO,
            ElementType.MARKET_FACE,
            ElementType.ONLINE_FILE,
        }
        cached = next(
            (
                message for message in cached_messages
                if any(element.type in media_types for element in message.elements)
            ),
            None,
        )
        if not cached:
            return

        for element in elements:
            if element.type != ElementType.QUOTE:
                continue
            quoted = element.content.get('quoted_elements', [])
            if any(item.type in media_types for item in quoted):
                continue
            element.content['quoted_elements'] = cached.elements
            element.content['quote_cache_enriched'] = True

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
            avatar=profile.avatar_url or public_user_avatar_url(profile.qq_num),
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
            avatar=(
                profile.avatar_url if profile and profile.avatar_url
                else public_user_avatar_url(mapping.qq_num)
            ),
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
        member = (
            self.dbman.session.query(GroupMember)
            .filter(GroupMember.group_number == group_num)
            .filter(GroupMember.uid == uid)
            .first()
        )
        if not member or not member.uid:
            return None
        return self._build_group_member(
            str(uid), member, {}, self.dbman.group_owner_uid(group_num)
        )

    @staticmethod
    def _collect_group_senders(query) -> dict[str, dict]:
        """轻量预扫实际发送者，并保留消息行中的最新可用资料。"""
        model = query.column_descriptions[0]['entity']
        rows = (
            query.order_by(None)
            .with_entities(
                model.id,
                model.sender_uid,
                model.sender_num,
                model.nickname,
                model.group_name_card,
                model.time,
            )
            .yield_per(GROUP_SENDER_SCAN_BATCH_SIZE)
        )
        senders: dict[str, dict] = {}
        for msg_id, sender_uid, sender_num, nickname, card, timestamp in rows:
            platform_id = normalize_sender_id(sender_uid, sender_num, msg_id)
            current_key = (timestamp or 0, msg_id or 0)
            sender = senders.setdefault(platform_id, {
                'lookup_uid': str(sender_uid) if sender_uid else None,
                'qq_num': sender_num or 0,
                'nickname': nickname or '',
                'group_nickname': card or '',
                '_qq_latest': current_key if sender_num else (-1, -1),
                '_nickname_latest': current_key if nickname else (-1, -1),
                '_card_latest': current_key if card else (-1, -1),
            })
            if sender_uid and not sender['lookup_uid']:
                sender['lookup_uid'] = str(sender_uid)
            if sender_num and current_key >= sender['_qq_latest']:
                sender['qq_num'] = sender_num
                sender['_qq_latest'] = current_key
            if nickname and current_key >= sender['_nickname_latest']:
                sender['nickname'] = nickname
                sender['_nickname_latest'] = current_key
            if card and current_key >= sender['_card_latest']:
                sender['group_nickname'] = card
                sender['_card_latest'] = current_key
        return senders

    def _get_group_member_rows(
        self,
        group_num: int,
        uids: set[str],
    ) -> dict[str, GroupMember]:
        """分块批量查询群成员，避免超过 SQLite 参数数量限制。"""
        result = {}
        ordered_uids = sorted(uid for uid in uids if uid)
        try:
            for start in range(
                0, len(ordered_uids), GROUP_MEMBER_QUERY_CHUNK_SIZE
            ):
                chunk = ordered_uids[
                    start:start + GROUP_MEMBER_QUERY_CHUNK_SIZE
                ]
                rows = (
                    self.dbman.session.query(GroupMember)
                    .filter(GroupMember.group_number == group_num)
                    .filter(GroupMember.uid.in_(chunk))
                    .all()
                )
                result.update({
                    str(member.uid): member
                    for member in rows
                    if member.uid
                })
        except SQLAlchemyError as exc:
            logger.warning(
                "读取群 %s 成员资料失败，使用消息行降级: %s",
                group_num,
                exc,
            )
        return result

    @staticmethod
    def _build_group_member(
        platform_id: str,
        member,
        fallback: dict,
        owner_uid: Optional[str],
    ) -> ParsedMember:
        qq_num = (
            getattr(member, 'qq_num', None)
            or fallback.get('qq_num')
            or 0
        )
        nickname = (
            getattr(member, 'nickname', None)
            or fallback.get('nickname')
            or str(qq_num or platform_id)
        )
        group_nickname = (
            getattr(member, 'group_name_card', None)
            or fallback.get('group_nickname')
            or None
        )
        member_uid = str(getattr(member, 'uid', '') or platform_id)
        return ParsedMember(
            platform_id=member_uid,
            qq_num=qq_num,
            nickname=nickname,
            group_nickname=group_nickname,
            is_owner=bool(owner_uid and member_uid == str(owner_uid)),
            is_admin=getattr(member, 'manager_flag', None) == 1,
            avatar=(
                fallback.get('avatar')
                or public_user_avatar_url(qq_num)
            ),
        )

    @staticmethod
    def _enrich_with_self(
        member: ParsedMember,
        self_member: ParsedMember,
    ) -> None:
        """用当前账号资料补齐群成员降级值，不覆盖群内资料与角色。"""
        fallback_names = {
            '',
            str(member.platform_id),
            str(member.qq_num or ''),
        }
        if member.nickname in fallback_names and self_member.nickname:
            member.nickname = self_member.nickname
        if not member.qq_num and self_member.qq_num:
            member.qq_num = self_member.qq_num
        if not member.avatar:
            member.avatar = self_member.avatar

    def get_group_conversation_members(
        self,
        group_num: int,
        query,
        owner_uid: Optional[str] = None,
    ) -> list[ParsedMember]:
        """只解析本次导出的发送者，并额外保证群主和当前账号可关联。"""
        sender_fallbacks = self._collect_group_senders(query)
        self_member = self.get_self_member()
        lookup_uids = {
            fallback['lookup_uid']
            for fallback in sender_fallbacks.values()
            if fallback.get('lookup_uid')
        }
        if owner_uid:
            lookup_uids.add(str(owner_uid))
        if self_member:
            lookup_uids.add(str(self_member.platform_id))
        member_rows = self._get_group_member_rows(group_num, lookup_uids)

        members: dict[str, ParsedMember] = {}
        for platform_id, fallback in sender_fallbacks.items():
            lookup_uid = fallback.get('lookup_uid')
            member = self._build_group_member(
                platform_id,
                member_rows.get(lookup_uid) if lookup_uid else None,
                fallback,
                owner_uid,
            )
            members[member.platform_id] = member

        if owner_uid:
            owner_id = str(owner_uid)
            if owner_id in members:
                members[owner_id].is_owner = True
            else:
                members[owner_id] = self._build_group_member(
                    owner_id, member_rows.get(owner_id), {}, owner_id
                )

        if self_member:
            self_id = str(self_member.platform_id)
            if self_id not in members:
                members[self_id] = self._build_group_member(
                    self_id,
                    member_rows.get(self_id),
                    {
                        'qq_num': self_member.qq_num,
                        'nickname': self_member.nickname,
                        'group_nickname': self_member.group_nickname,
                        'avatar': self_member.avatar,
                    },
                    owner_uid,
                )
            self._enrich_with_self(members[self_id], self_member)

        return list(members.values())

    def get_all_group_members(self, group_num: int) -> list[ParsedMember]:
        """获取群成员表中的全部成员（兼容旧调用；导出不使用）。

        Args:
            group_num: 群号

        Returns:
            ParsedMember 列表
        """
        members = (
            self.dbman.session.query(GroupMember)
            .filter(GroupMember.group_number == group_num)
            .filter(GroupMember.uid.is_not(None))
            .filter(GroupMember.uid != '')
            .all()
        )

        owner_uid = self.dbman.group_owner_uid(group_num)
        result = []
        for member in members:
            result.append(self._build_group_member(
                str(member.uid), member, {}, owner_uid
            ))

        return result
