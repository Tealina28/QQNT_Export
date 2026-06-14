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
        try:
            for element in msg.elements.elements:
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
