"""
数据模型定义

解析层的核心数据结构，与具体导出格式无关。
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class ElementType(IntEnum):
    """消息元素类型枚举"""
    TEXT = 1
    IMAGE = 2
    FILE = 3
    VOICE = 4
    VIDEO = 5
    EMOJI = 6
    QUOTE = 7
    NOTICE = 8
    RED_PACKET = 9
    APPLICATION = 10
    MARKET_FACE = 11    # 商城表情
    MARKDOWN = 14       # markdown 消息
    XML = 16            # XML 消息
    CALL = 21
    FEED = 26
    BUBBLE_FACE = 27    # 弹射/平底锅表情
    LOCATION = 28       # 位置共享
    BOT = 44            # 机器人对话
    OTHER = 99


@dataclass
class ParsedElement:
    """解析后的消息元素

    Attributes:
        type: 元素类型（枚举）
        content: 元素内容（灵活的字典结构，不同类型有不同字段）
    """
    type: ElementType
    content: dict = field(default_factory=dict)

    def __repr__(self):
        return f"ParsedElement(type={self.type.name}, content={self.content})"


@dataclass
class ParsedMessage:
    """解析后的消息

    Attributes:
        msg_id: 消息 ID
        seq: 消息序列号
        sender_uid: 发送者 UID
        sender_num: 发送者 QQ 号
        timestamp: 时间戳（秒级）
        elements: 消息元素列表
        quoted_msg_id: 引用的消息 seq（可选）
        group_num: 群号（群聊消息）
        sender_nickname: 发送者昵称（群聊）
        sender_card: 发送者群名片（群聊）
    """
    msg_id: str
    seq: int
    sender_uid: str
    sender_num: int
    timestamp: int
    elements: list[ParsedElement]
    quoted_msg_id: Optional[str] = None
    # 群聊特有字段
    group_num: Optional[int] = None
    sender_nickname: Optional[str] = None
    sender_card: Optional[str] = None

    def is_group_message(self) -> bool:
        """判断是否为群聊消息"""
        return self.group_num is not None


@dataclass
class ParsedMember:
    """解析后的成员信息

    Attributes:
        platform_id: 平台 ID（UID）
        qq_num: QQ 号
        nickname: 昵称
        remark: 备注名
        group_nickname: 群昵称（群聊成员）
        is_owner: 是否为群主
        is_admin: 是否为管理员
    """
    platform_id: str
    qq_num: int
    nickname: str
    remark: Optional[str] = None
    # 群聊特有字段
    group_nickname: Optional[str] = None
    is_owner: bool = False
    is_admin: bool = False

    def get_display_name(self) -> str:
        """获取显示名称（优先级：备注 > 群昵称 > 昵称）"""
        return self.remark or self.group_nickname or self.nickname or str(self.qq_num)
