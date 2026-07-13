"""
ChatLab JSON 格式导出器

符合 ChatLab v0.0.2 格式规范的 JSON 导出器。
"""

import json
import logging
import time
from typing import Any, Optional

from parser.models import ParsedMessage, ParsedMember, ElementType
from .base import BaseExporter


logger = logging.getLogger(__name__)


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

        # 构建成员映射
        member_map = {m.platform_id: m for m in members}

        messages_data = self._build_messages(messages, member_map)

        data = {
            "chatlab": {
                "version": "0.0.2",
                "exportedAt": int(time.time()),
                "generator": "QQNT_Export"
            },
            "meta": self._build_meta(meta),
            "members": self._build_members(members),
            "messages": messages_data
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
            if not member.platform_id:
                logger.warning(
                    'skip member without platform id: qq_num=%s nickname=%r',
                    member.qq_num,
                    member.nickname,
                )
                continue
            member_data = {
                "platformId": str(member.platform_id),
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
        member_map: dict[str, ParsedMember],
        *_legacy_args: object,
    ) -> list[dict[str, Any]]:
        """构建 messages 字段。"""
        result = []
        for msg in messages:
            message_data = {
                "platformMessageId": msg.msg_id,
                "sender": msg.sender_uid,
                "accountName": self._get_account_name(msg, member_map),
                "timestamp": msg.timestamp,
                "type": self._infer_message_type(msg.elements),
                "content": self._build_content(msg.elements, member_map)
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

    def _resolve_name(
        self,
        uid: str,
        member_map: dict[str, ParsedMember]
    ) -> Optional[str]:
        """将 UID 解析为显示名，找不到则返回 None"""
        if not uid:
            return None
        member = member_map.get(uid)
        if member:
            return member.get_display_name()
        return None

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
        semantic_elements = [
            element for element in elements
            if not element.content.get('recovered_message_body')
        ]
        if semantic_elements:
            elements = semantic_elements

        if not elements:
            return 99  # OTHER

        # 新版转发使用 MULTI_MSG(16)，旧版数据可能是带 40900 的 Ark(10)。
        if any(
            element.type == ElementType.MULTI_MSG
            or (
                element.type == ElementType.APPLICATION
                and element.content.get('forward_messages')
            )
            for element in elements
        ):
            return 26  # FORWARD

        for element in elements:
            if element.type == ElementType.RED_PACKET:
                if element.content.get('wallet_type') == 'transfer':
                    return 21  # TRANSFER
            elif element.type == ElementType.NOTICE:
                notice_type = element.content.get('notice_type')
                if notice_type == 'withdraw':
                    return 81  # RECALL
                if notice_type == 'interactive':
                    return 22  # POKE
            elif (
                element.type == ElementType.MARKDOWN
                and element.content.get('flash_transfer')
            ):
                return 4  # FILE
            elif element.type == ElementType.APPLICATION:
                card_kind = element.content.get('card_kind')
                if card_kind == 'location':
                    return 8  # LOCATION
                if card_kind == 'contact':
                    return 27  # CONTACT
                if card_kind == 'announcement':
                    return 80  # SYSTEM

        # ChatLab 类型映射
        type_mapping = {
            ElementType.TEXT: 0,        # TEXT
            ElementType.IMAGE: 1,       # IMAGE
            ElementType.VOICE: 2,       # VOICE
            ElementType.VIDEO: 3,       # VIDEO
            ElementType.FILE: 4,        # FILE
            ElementType.ONLINE_FILE: 4, # FILE
            ElementType.ONLINE_FOLDER: 4, # FILE
            ElementType.EMOJI: 5,       # EMOJI
            ElementType.MARKET_FACE: 5, # EMOJI（商城表情）
            ElementType.BUBBLE_FACE: 5, # EMOJI（弹射表情）
            ElementType.QUOTE: 25,      # REPLY
            ElementType.NOTICE: 80,     # SYSTEM
            ElementType.RED_PACKET: 20, # RED_PACKET
            ElementType.APPLICATION: 24,# SHARE
            ElementType.CALL: 23,       # CALL
            ElementType.FEED: 24,       # SHARE
            ElementType.MARKDOWN: 0,    # TEXT（markdown）
            ElementType.MARKDOWN_BUTTON: 99, # OTHER（Bot 按钮）
            ElementType.BOT: 0,         # TEXT（机器人对话）
            ElementType.MULTI_MSG: 26,  # FORWARD
            ElementType.LOCATION: 8,    # LOCATION
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

    def _build_content(
        self,
        elements: list,
        member_map: Optional[dict[str, ParsedMember]] = None
    ) -> Optional[str]:
        """构建消息内容字符串

        将多个元素合并为一个字符串展示。member_map 用于把撤回/拍一拍等
        提示中的 UID 解析为显示名。
        """
        if not elements:
            return None

        member_map = member_map or {}
        parts = []

        for elem in elements:
            if elem.content.get('recovered_message_body'):
                continue
            if elem.type == ElementType.TEXT:
                parts.append(elem.content.get('text', ''))

            elif elem.type == ElementType.IMAGE:
                img = self._format_image(elem.content)
                if img:
                    parts.append(img)

            elif elem.type in (ElementType.FILE, ElementType.ONLINE_FILE):
                filename = elem.content.get('filename', '')
                parts.append(f"[文件: {filename}]" if filename else "[文件]")

            elif elem.type == ElementType.ONLINE_FOLDER:
                filename = elem.content.get('filename', '')
                parts.append(f"[文件夹: {filename}]" if filename else "[文件夹]")

            elif elem.type == ElementType.VOICE:
                text = elem.content.get('text', '')
                if text:
                    parts.append(f"[语音: {text}]")
                else:
                    parts.append("[语音]")

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
                parts.append(self._format_notice(elem.content, member_map))

            elif elem.type == ElementType.RED_PACKET:
                prompt = elem.content.get('prompt', '')
                label = "转账" if elem.content.get('wallet_type') == 'transfer' else "红包"
                parts.append(f"[{label}: {prompt}]" if prompt else f"[{label}]")

            elif elem.type == ElementType.CALL:
                text = elem.content.get('text', '')
                parts.append(text if text else "[通话]")

            elif elem.type == ElementType.FEED:
                title = elem.content.get('title', '')
                subtitle = elem.content.get('subtitle', '') or elem.content.get('content', '')
                detail = f"{title}{(' | ' + subtitle) if subtitle else ''}"
                parts.append(f"[动态: {detail}]" if detail else "[动态]")

            elif elem.type == ElementType.APPLICATION:
                parts.append(self._format_application(elem.content))

            elif elem.type == ElementType.MULTI_MSG:
                parts.append("[合并转发]")

            elif elem.type == ElementType.MARKET_FACE:
                text = elem.content.get('text', '')
                if not text:
                    parts.append("[商城表情]")
                elif text.startswith('['):
                    # 外显文本通常已自带方括号，如 "[贴贴]"
                    parts.append(text)
                else:
                    parts.append(f"[{text}]")

            elif elem.type == ElementType.BUBBLE_FACE:
                # 优先外显摘要，缺失时回退到普通表情文本
                text = elem.content.get('summary') or elem.content.get('emoji_text')
                parts.append(text if text else "[表情]")

            elif elem.type == ElementType.MARKDOWN or elem.type == ElementType.BOT:
                flash = elem.content.get('flash_transfer')
                if flash:
                    filename = flash.get('thumbnail_name') or flash.get('file_set_id')
                    parts.append(f"[闪传: {filename}]" if filename else "[闪传文件]")
                else:
                    text = elem.content.get('summary') or elem.content.get('text', '')
                    parts.append(text if text else "[消息]")

            elif elem.type == ElementType.MARKDOWN_BUTTON:
                labels = [
                    button.get('label', '')
                    for row in elem.content.get('rows', [])
                    for button in row
                    if button.get('label')
                ]
                if labels:
                    parts.append(f"[按钮: {' | '.join(labels)}]")

            elif elem.type == ElementType.LOCATION:
                text = elem.content.get('text', '')
                parts.append(f"[位置: {text}]" if text else "[位置共享]")

            else:
                parts.append("[未知消息]")

        content = '\n'.join(parts)
        return content if content else None

    def _format_image(self, c: dict[str, Any]) -> Optional[str]:
        """格式化图片元素的展示文本

        - 闪照 → [闪照]
        - 特殊动画表情（sub_type=7）→ 表情描述
        - 普通图片有描述 → [图片: 描述]
        - 普通图片无描述 → None（由 type 字段体现为图片）
        """
        text = c.get('text', '')
        if c.get('is_flash') == 1:
            return f"[闪照: {text}]" if text else "[闪照]"
        if c.get('sub_type') == 7 and text:
            # 特殊动画表情，描述本身即外显内容
            return text
        if text:
            return f"[图片: {text}]"
        return None

    def _format_notice(
        self,
        c: dict[str, Any],
        member_map: dict[str, ParsedMember]
    ) -> str:
        """格式化系统提示（撤回 / 拍一拍 / 普通灰字）"""
        ntype = c.get('notice_type')

        if ntype == 'withdraw':
            name = (self._resolve_name(c.get('recaller_uid'), member_map)
                    or c.get('recaller_name') or "某人")
            return c.get('display_text') or f"[{name} 撤回了一条消息]"

        if ntype == 'interactive':
            actor = (self._resolve_name(c.get('actor_uid'), member_map)
                     or c.get('actor_name') or "某人")
            target = (self._resolve_name(c.get('target_uid'), member_map)
                      or c.get('target_name') or "某人")
            return c.get('text') or f"{actor} 戳了戳 {target}"

        if ntype == 'invite':
            actor = (self._resolve_name(c.get('actor_uid'), member_map)
                     or c.get('actor_name') or "某人")
            target = (self._resolve_name(c.get('target_uid'), member_map)
                      or c.get('target_name') or "某人")
            return c.get('text') or f"{actor} 邀请了 {target}"

        if ntype == 'group':
            if c.get('mute_info'):
                mute = c['mute_info']
                target = (self._resolve_name(mute.get('target_uid'), member_map)
                          or mute.get('target_name') or "某人")
                duration = mute.get('duration') or 0
                return c.get('text') or f"{target} 被禁言 {duration} 秒"
            event = c.get('group_event')
            user = (self._resolve_name(c.get('user1_uid'), member_map)
                    or c.get('user1_name') or "某人")
            fallback = {
                'join': f"{user} 加入了群聊",
                'dismiss': "群聊已解散",
                'remove': f"{user} 被移出群聊",
            }.get(event, "[群提示]")
            return c.get('text') or fallback

        text = c.get('text', '')
        return text if text else "[系统提示]"

    def _format_application(self, c: dict[str, Any]) -> str:
        """格式化 Ark 卡片消息，按 app 类型路由（音乐/位置/合并转发/名片等）"""
        kind = c.get('card_kind')
        title = c.get('title') or c.get('prompt') or ''
        description = c.get('description') or ''
        detail = f"{title}{(' | ' + description) if description else ''}".strip()

        labels = {
            'location': '位置',
            'contact': '名片',
            'announcement': '群公告',
            'music': '音乐',
            'miniapp': '小程序',
            'forward': '聊天记录',
            'share': '分享',
        }
        label = labels.get(kind, '应用消息')
        return f"[{label}: {detail}]" if detail else f"[{label}]"
