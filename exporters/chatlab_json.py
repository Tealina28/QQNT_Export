"""
ChatLab JSON 格式导出器

符合 ChatLab v0.0.2 格式规范的 JSON 导出器。
"""

import json
import time
from typing import Any, Optional

from parser.models import ParsedMessage, ParsedMember, ElementType
from .base import BaseExporter


class ChatLabJSONExporter(BaseExporter):
    """ChatLab JSON 格式导出器"""

    def export(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
        messages: list[ParsedMessage]
    ):
        """导出为 ChatLab JSON 格式"""
        self.ensure_output_dir()

        data = {
            "chatlab": {
                "version": "0.0.2",
                "exportedAt": int(time.time()),
                "generator": "QQNT_Export"
            },
            "meta": self._build_meta(meta),
            "members": self._build_members(members),
            "messages": self._build_messages(messages, members)
        }

        with open(self.output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_file_extension(self) -> str:
        return '.json'

    def _build_meta(self, meta: dict[str, Any]) -> dict[str, Any]:
        """构建 meta 字段"""
        result = {
            "name": meta['name'],
            "platform": meta.get('platform', 'qq'),
            "type": meta['type']  # 'group' or 'private'
        }

        # 可选字段
        if 'groupId' in meta:
            result['groupId'] = str(meta['groupId'])
        if 'ownerId' in meta:
            result['ownerId'] = str(meta['ownerId'])

        return result

    def _build_members(self, members: list[ParsedMember]) -> list[dict[str, Any]]:
        """构建 members 字段"""
        result = []

        for member in members:
            member_data = {
                "platformId": member.platform_id,
                "accountName": member.nickname or str(member.qq_num),
            }

            # 可选字段
            if member.group_nickname:
                member_data["groupNickname"] = member.group_nickname

            # 角色
            roles = []
            if member.is_owner:
                roles.append({"id": "owner"})
            if member.is_admin:
                roles.append({"id": "admin"})

            if roles:
                member_data["roles"] = roles

            result.append(member_data)

        return result

    def _build_messages(
        self,
        messages: list[ParsedMessage],
        members: list[ParsedMember]
    ) -> list[dict[str, Any]]:
        """构建 messages 字段"""
        # 构建成员查询字典（用于快速查找）
        member_map = {m.platform_id: m for m in members}

        result = []
        for msg in messages:
            message_data = {
                "platformMessageId": msg.msg_id,
                "sender": msg.sender_uid,
                "accountName": self._get_account_name(msg, member_map),
                "timestamp": msg.timestamp,
                "type": self._infer_message_type(msg.elements),
                "content": self._build_content(msg.elements)
            }

            # 可选字段：引用消息
            if msg.quoted_msg_id:
                message_data["replyToMessageId"] = msg.quoted_msg_id

            # 群聊特有字段
            if msg.is_group_message():
                group_nickname = msg.sender_card or msg.sender_nickname
                if group_nickname:
                    message_data["groupNickname"] = group_nickname

            result.append(message_data)

        return result

    def _get_account_name(
        self,
        msg: ParsedMessage,
        member_map: dict[str, ParsedMember]
    ) -> str:
        """获取账号名称"""
        member = member_map.get(msg.sender_uid)
        if member:
            return member.nickname or str(member.qq_num)

        # 回退：使用消息中的昵称或 QQ 号
        return msg.sender_nickname or str(msg.sender_num)

    def _infer_message_type(self, elements: list) -> int:
        """推断消息类型（ChatLab 类型码）

        策略：
        1. 如果只有一个元素，返回该元素的类型
        2. 如果多个元素，优先返回非文本元素的类型
        3. 如果都是文本，返回 TEXT (0)
        """
        if not elements:
            return 99  # OTHER

        # ChatLab 类型映射
        type_mapping = {
            ElementType.TEXT: 0,        # TEXT
            ElementType.IMAGE: 1,       # IMAGE
            ElementType.VOICE: 2,       # VOICE
            ElementType.VIDEO: 3,       # VIDEO
            ElementType.FILE: 4,        # FILE
            ElementType.EMOJI: 5,       # EMOJI
            ElementType.QUOTE: 25,      # REPLY
            ElementType.NOTICE: 80,     # SYSTEM
            ElementType.RED_PACKET: 20, # RED_PACKET
            ElementType.APPLICATION: 24,# SHARE
            ElementType.CALL: 23,       # CALL
            ElementType.FEED: 24,       # SHARE
            ElementType.OTHER: 99,      # OTHER
        }

        # 单个元素：直接返回
        if len(elements) == 1:
            return type_mapping.get(elements[0].type, 99)

        # 多个元素：优先非文本元素
        non_text_elements = [e for e in elements if e.type != ElementType.TEXT]
        if non_text_elements:
            return type_mapping.get(non_text_elements[0].type, 99)

        # 都是文本
        return 0

    def _build_content(self, elements: list) -> Optional[str]:
        """构建消息内容字符串

        将多个元素合并为一个字符串展示。
        """
        if not elements:
            return None

        parts = []

        for elem in elements:
            if elem.type == ElementType.TEXT:
                parts.append(elem.content.get('text', ''))

            elif elem.type == ElementType.IMAGE:
                text = elem.content.get('text', '')
                if text:
                    # 有描述文本时显示
                    parts.append(f"[图片: {text}]")
                else:
                    # 无描述文本时，跳过（最终返回 null）
                    pass

            elif elem.type == ElementType.FILE:
                filename = elem.content.get('filename', '')
                parts.append(f"[文件: {filename}]" if filename else "[文件]")

            elif elem.type == ElementType.VOICE:
                duration = elem.content.get('duration', 0)
                text = elem.content.get('text', '')
                if text:
                    parts.append(f"[语音: {text}]")
                else:
                    parts.append(f"[语音 {duration}秒]")

            elif elem.type == ElementType.VIDEO:
                filename = elem.content.get('filename', '')
                parts.append(f"[视频: {filename}]" if filename else "[视频]")

            elif elem.type == ElementType.EMOJI:
                text = elem.content.get('text', '')
                parts.append(f"[{text}]" if text else "[表情]")

            elif elem.type == ElementType.QUOTE:
                # 引用元素本身不在 content 中显示
                # 引用关系通过 replyToMessageId 字段体现
                # 如果有其他文本元素，会在外层显示
                pass

            elif elem.type == ElementType.NOTICE:
                text = elem.content.get('text', '')
                parts.append(text if text else "[系统提示]")

            elif elem.type == ElementType.RED_PACKET:
                prompt = elem.content.get('prompt', '')
                parts.append(f"[红包: {prompt}]" if prompt else "[红包]")

            elif elem.type == ElementType.CALL:
                text = elem.content.get('text', '')
                parts.append(text if text else "[通话]")

            elif elem.type == ElementType.FEED:
                title = elem.content.get('title', '')
                parts.append(f"[动态: {title}]" if title else "[动态]")

            elif elem.type == ElementType.APPLICATION:
                parts.append("[应用消息]")

            else:
                parts.append("[未知消息]")

        content = '\n'.join(parts)
        return content if content else None
