"""
消息解析器

将数据库中的消息对象转换为统一的 ParsedMessage 对象。
"""

from typing import Optional

from db import DatabaseManager
from db.models import C2cMessage, GroupMessage, ProfileInfo, GroupMember
from .models import ParsedMessage, ParsedMember, ParsedElement
from .elements import ElementParser


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
        elements = self._parse_elements(msg)

        return ParsedMessage(
            msg_id=str(msg.id),
            sender_uid=msg.sender_uid,
            sender_num=msg.sender_num,
            timestamp=msg.time,
            elements=elements,
            quoted_msg_id=str(msg.quoted_seq) if msg.quoted_seq else None,
        )

    def parse_group_message(self, msg: GroupMessage) -> ParsedMessage:
        """解析群聊消息

        Args:
            msg: GroupMessage 对象

        Returns:
            ParsedMessage 对象
        """
        elements = self._parse_elements(msg)

        return ParsedMessage(
            msg_id=str(msg.id),
            sender_uid=msg.sender_uid,
            sender_num=msg.sender_num,
            timestamp=msg.time,
            elements=elements,
            quoted_msg_id=str(msg.quoted_seq) if msg.quoted_seq else None,
            # 群聊特有字段
            group_num=msg.mixed_group_num,
            sender_nickname=msg.nickname,
            sender_card=msg.group_name_card,
        )

    def _parse_elements(self, msg) -> list[ParsedElement]:
        """解析消息中的所有元素

        Args:
            msg: C2cMessage 或 GroupMessage 对象

        Returns:
            ParsedElement 列表
        """
        elements = []
        # 提取 40900 字段（合并转发缓存，仅当 msg_type==8 时有效）
        forward_cache = None
        if hasattr(msg, 'msg_type') and msg.msg_type == 8 and hasattr(msg, 'UNK_18'):
            forward_cache = msg.UNK_18

        try:
            for element in msg.elements.elements:
                # type=10 需要传入 forward_cache
                if element.type == 10:
                    parsed = ElementParser.parse(element, forward_cache)
                else:
                    parsed = ElementParser.parse(element)
                if parsed:
                    elements.append(parsed)
        except Exception as e:
            # 解析失败时返回空列表，避免崩溃
            pass

        return elements

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

        if not member:
            return None

        # 角色判断：根据 QQ 的实际情况
        # manager_flag: 0=普通成员, 1=管理员, 2=群主（推测，需实际数据验证）
        is_owner = False
        is_admin = False
        if hasattr(member, 'manager_flag'):
            if member.manager_flag == 2:
                is_owner = True
            elif member.manager_flag == 1:
                is_admin = True

        return ParsedMember(
            platform_id=member.uid,
            qq_num=member.qq_num,
            nickname=member.nickname or "",
            group_nickname=member.group_name_card,
            is_owner=is_owner,
            is_admin=is_admin,
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
            .all()
        )

        result = []
        for member in members:
            # 角色判断
            is_owner = False
            is_admin = False
            if hasattr(member, 'manager_flag'):
                if member.manager_flag == 2:
                    is_owner = True
                elif member.manager_flag == 1:
                    is_admin = True

            parsed = ParsedMember(
                platform_id=member.uid,
                qq_num=member.qq_num,
                nickname=member.nickname or "",
                group_nickname=member.group_name_card,
                is_owner=is_owner,
                is_admin=is_admin,
            )
            result.append(parsed)

        return result
