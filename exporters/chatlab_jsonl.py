"""
ChatLab JSONL 格式导出器

符合 ChatLab v0.0.2 格式规范的 JSONL 流式导出器，适用于超大规模数据。
"""

import json
import time
from collections.abc import Iterable
from typing import Any

from parser.models import ParsedMessage, ParsedMember
from .chatlab_json import ChatLabJSONExporter


class ChatLabJSONLExporter(ChatLabJSONExporter):
    """ChatLab JSONL 格式导出器（流式写入）

    继承自 ChatLabJSONExporter，复用 meta/members/messages 的构建逻辑，
    但以流式方式写入 JSONL 格式。
    """

    streams_messages = True
    supports_incremental_messages = True

    def __init__(self, output_path, config):
        super().__init__(output_path, config)
        self._stream = None
        self._stream_member_map: dict[str, ParsedMember] = {}

    def export(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
        messages: Iterable[ParsedMessage]
    ):
        """导出为 ChatLab JSONL 格式（流式写入）"""
        self.start_stream(meta, members)
        try:
            for msg in messages:
                self.write_message(msg)
        except Exception:
            self.abort_stream()
            raise
        else:
            self.finish_stream()

    def start_stream(
        self,
        meta: dict[str, Any],
        members: list[ParsedMember],
    ) -> None:
        self.ensure_output_dir()
        self._stream_member_map = {member.platform_id: member for member in members}
        self._stream = open(self.output_path, 'w', encoding='utf-8')
        header = {
            "_type": "header",
            "chatlab": {
                "version": "0.0.2",
                "exportedAt": int(time.time()),
                "generator": "QQNT_Export"
            },
            "meta": self._build_meta(meta)
        }
        self._stream.write(json.dumps(header, ensure_ascii=False) + '\n')
        for member_data in self._build_members(members):
            member_line = {"_type": "member", **member_data}
            self._stream.write(json.dumps(member_line, ensure_ascii=False) + '\n')

    def write_message(self, message: ParsedMessage) -> None:
        if self._stream is None:
            raise RuntimeError('JSONL stream is not open')
        message_line = {
            "_type": "message",
            **self._build_single_message(message, self._stream_member_map),
        }
        self._stream.write(json.dumps(message_line, ensure_ascii=False) + '\n')

    def finish_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def abort_stream(self) -> None:
        self.finish_stream()

    def get_file_extension(self) -> str:
        return '.jsonl'

    def _build_single_message(
        self,
        msg: ParsedMessage,
        member_map: dict[str, ParsedMember],
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

        return message_data
