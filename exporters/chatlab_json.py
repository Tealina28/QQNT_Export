"""
ChatLab JSON 格式导出器

符合 ChatLab v0.0.2 格式规范的 JSON 导出器。
"""

import json
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from parser.models import ParsedMessage, ParsedMember, ElementType
from parser.elements import compute_image_cache_path
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

        # 初始化资源目录（为 HTML 导出做准备，但不在 ChatLab JSON 中体现）
        resources_dir = self.output_path.parent / 'resources'
        resources_dir.mkdir(exist_ok=True)
        for subdir in ['images', 'videos', 'audios', 'files']:
            (resources_dir / subdir).mkdir(exist_ok=True)

        # 构建成员映射
        member_map = {m.platform_id: m for m in members}

        # 构建消息并落地资源
        messages_data = self._build_messages(messages, member_map, resources_dir)

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
        member_map: dict[str, ParsedMember],
        resources_dir: Path
    ) -> list[dict[str, Any]]:
        """构建 messages 字段并落地资源"""
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

            # 落地图片资源（不在 ChatLab JSON 中体现，为 HTML 导出做准备）
            self._copy_image_resources(msg.elements, resources_dir)

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
            ElementType.MARKET_FACE: 5, # EMOJI（商城表情）
            ElementType.BUBBLE_FACE: 5, # EMOJI（弹射表情）
            ElementType.QUOTE: 25,      # REPLY
            ElementType.NOTICE: 80,     # SYSTEM
            ElementType.RED_PACKET: 20, # RED_PACKET
            ElementType.APPLICATION: 24,# SHARE
            ElementType.CALL: 23,       # CALL
            ElementType.FEED: 24,       # SHARE
            ElementType.MARKDOWN: 0,    # TEXT（markdown）
            ElementType.BOT: 0,         # TEXT（机器人对话）
            ElementType.XML: 99,        # OTHER
            ElementType.LOCATION: 99,   # OTHER（位置共享）
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
            if elem.type == ElementType.TEXT:
                parts.append(elem.content.get('text', ''))

            elif elem.type == ElementType.IMAGE:
                img = self._format_image(elem.content)
                if img:
                    parts.append(img)

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
                parts.append(self._format_notice(elem.content, member_map))

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
                parts.append(self._format_application(elem.content))

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
                text = elem.content.get('text', '')
                parts.append(text if text else "[消息]")

            elif elem.type == ElementType.XML:
                xml = elem.content.get('xml', '')
                parts.append(xml if xml else "[XML消息]")

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
            suffix = c.get('suffix') or ''
            return f"[{name} 撤回了一条消息{(' ' + suffix) if suffix else ''}]"

        if ntype == 'interactive':
            actor = self._resolve_name(c.get('actor_uid'), member_map) or "某人"
            target = self._resolve_name(c.get('target_uid'), member_map) or "某人"
            verb = c.get('verb') or "戳了戳"
            suffix = c.get('suffix') or ''
            return f"{actor} {verb} {target}{suffix}"

        text = c.get('text', '')
        return text if text else "[系统提示]"

    def _format_application(self, c: dict[str, Any]) -> str:
        """格式化 Ark 卡片消息，按 app 类型路由（音乐/位置/合并转发/名片等）"""
        import json as _json

        raw = c.get('raw')
        if not raw:
            return "[应用消息]"
        try:
            data = _json.loads(raw.decode('utf-8', 'ignore') if isinstance(raw, bytes) else raw)
        except Exception:
            return "[应用消息]"

        app = data.get('app', '')
        prompt = data.get('prompt', '') or ''
        meta = data.get('meta', {}) or {}

        if app == "com.tencent.map" and data.get('view') == "LocationShare":
            loc = meta.get('Location.Search', {}) or {}
            name = loc.get('name') or "未知地点"
            address = loc.get('address') or ""
            return f"[位置: {name}{(' | ' + address) if address else ''}]"

        if app == "com.tencent.music.lua" and data.get('view') == "music":
            music = meta.get('music', {}) or {}
            title = music.get('title') or ""
            artist = music.get('desc') or ""
            return f"[分享] {title}{(' - ' + artist) if artist else ''}".strip()

        if app == "com.tencent.multimsg":
            detail = meta.get('detail', {}) or {}
            source = detail.get('source') or "聊天记录"
            summary = detail.get('summary') or "查看转发"
            return f"[聊天记录] {source}: {summary}"

        if app == "com.tencent.contact.lua":
            return f"[名片] {prompt}" if prompt else "[名片]"

        # 兜底：用 prompt 外显，否则标注应用消息
        return prompt if prompt else "[应用消息]"

    def _copy_image_resources(
        self,
        elements: list,
        resources_dir: Path
    ):
        """落地图片资源（不在 ChatLab JSON 中体现，为 HTML 导出做准备）

        Args:
            elements: ParsedElement 列表
            resources_dir: 资源根目录
        """
        pic_path = self.config.get('pic_path')
        pic_path_obj = Path(pic_path) if pic_path else None

        if not pic_path_obj:
            return

        for elem in elements:
            if elem.type == ElementType.IMAGE:
                md5 = elem.content.get('md5')
                original = elem.content.get('original', 0)
                if md5:
                    # 计算源路径
                    src_path = compute_image_cache_path(md5, original, pic_path_obj)
                    if src_path and src_path.exists():
                        # 目标路径：resources/images/{md5}.jpg
                        ext = src_path.suffix or '.jpg'
                        dst_filename = f"{md5}{ext}"
                        dst_path = resources_dir / 'images' / dst_filename

                        # 复制文件（去重：已存在则跳过）
                        if not dst_path.exists():
                            try:
                                shutil.copy2(src_path, dst_path)
                            except Exception:
                                pass  # 静默失败，不阻断导出
