"""
ChatLab JSONL 格式导出器

符合 ChatLab v0.0.2 格式规范的 JSONL 流式导出器，适用于超大规模数据。
"""

import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from parser.models import ParsedMessage, ParsedMember
from .chatlab_json import ChatLabJSONExporter


class ChatLabJSONLExporter(ChatLabJSONExporter):
    """ChatLab JSONL 格式导出器（流式写入）

    继承自 ChatLabJSONExporter，复用 meta/members/messages 的构建逻辑，
    但以流式方式写入 JSONL 格式。
    """

    streams_messages = True

    def export(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
        messages: Iterable[ParsedMessage]
    ):
        """导出为 ChatLab JSONL 格式（流式写入）"""
        self.ensure_output_dir()

        # 初始化资源目录（为 HTML 导出做准备，但不在 ChatLab JSON 中体现）
        resources_dir = self.output_path.parent / 'resources'
        resources_dir.mkdir(exist_ok=True)
        for subdir in ['images', 'videos', 'audios', 'files']:
            (resources_dir / subdir).mkdir(exist_ok=True)

        # 构建成员映射
        member_map = {m.platform_id: m for m in members}

        with open(self.output_path, 'w', encoding='utf-8') as f:
            # 1. 写入 header 行
            header = {
                "_type": "header",
                "chatlab": {
                    "version": "0.0.2",
                    "exportedAt": int(time.time()),
                    "generator": "QQNT_Export"
                },
                "meta": self._build_meta(meta)
            }
            f.write(json.dumps(header, ensure_ascii=False) + '\n')

            # 2. 写入 member 行
            member_data_list = self._build_members(members)
            for member_data in member_data_list:
                member_line = {
                    "_type": "member",
                    **member_data
                }
                f.write(json.dumps(member_line, ensure_ascii=False) + '\n')

            # 3. 流式写入 message 行
            for msg in messages:
                message_data = self._build_single_message(msg, member_map, resources_dir)
                message_line = {
                    "_type": "message",
                    **message_data
                }
                f.write(json.dumps(message_line, ensure_ascii=False) + '\n')

    def get_file_extension(self) -> str:
        return '.jsonl'

    def _build_single_message(
        self,
        msg: ParsedMessage,
        member_map: dict[str, ParsedMember],
        resources_dir: Path
    ) -> dict[str, Any]:
        """构建单条消息数据（用于流式写入）"""
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

        return message_data
