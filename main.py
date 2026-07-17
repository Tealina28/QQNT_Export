"""
QQNT Export - 重构版

解析和导出解耦的 QQNT 聊天记录导出工具。
"""

import hashlib
import logging
import re
import tomllib
from pathlib import Path
from sys import argv

from tqdm import tqdm

from db import DatabaseManager
from parser import MessageParser
from parser.references import ConversationReferenceResolver
from parser.dataline import (
    dataline_conversation_name,
    resolve_dataline_owner_id,
)
from parser.avatar import public_group_avatar_url
from exporters import EXPORTER_MAP


DEFAULT_STREAM_BATCH_SIZE = 1000
MAX_OUTPUT_STEM_BYTES = 240
MAX_IDENTIFIER_LABEL_BYTES = 64
WINDOWS_RESERVED_FILENAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{index}' for index in range(1, 10)),
    *(f'LPT{index}' for index in range(1, 10)),
}


class TqdmLoggingHandler(logging.Handler):
    """通过 tqdm.write 输出日志，避免与进度条互相冲刷"""

    def emit(self, record):
        try:
            tqdm.write(self.format(record))
            self.flush()
        except Exception:
            self.handleError(record)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[TqdmLoggingHandler()]
)


def sanitize_filename(filename) -> str:
    """生成跨平台安全且长度受限的单个文件名组件。"""
    return _sanitize_filename(filename, MAX_OUTPUT_STEM_BYTES)


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """按 UTF-8 字节数截断字符串，不切断多字节字符。"""
    if len(value.encode('utf-8')) <= max_bytes:
        return value
    return value.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore')


def _sanitize_filename(filename, max_bytes: int) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', str(filename))
    value = value.strip(' .')
    value = _truncate_utf8(value, max_bytes).rstrip(' .')
    if not value:
        value = 'conversation'
    if value.split('.', 1)[0].upper() in WINDOWS_RESERVED_FILENAMES:
        value = f'_{value}'
    return _truncate_utf8(value, max_bytes).rstrip(' .') or 'conversation'


def conversation_output_stem(display_name, stable_id) -> str:
    """组合可读会话名与稳定标识，避免清理及大小写规则造成覆盖。"""
    raw_id = str(stable_id)
    identifier = _sanitize_filename(raw_id, MAX_IDENTIFIER_LABEL_BYTES)
    identifier_hash = hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:16]
    suffix = f'__{identifier}-{identifier_hash}'
    display_budget = MAX_OUTPUT_STEM_BYTES - len(suffix.encode('utf-8'))
    display = _sanitize_filename(display_name, max(1, display_budget))
    return f'{display}{suffix}'


def create_output_dirs(
    base_path: Path,
    conversation_types: set[str] | None = None,
) -> tuple[Path, Path, Path]:
    """创建输出目录结构

    Returns:
        (c2c_path, group_path, dataline_path) 元组
    """
    c2c_path = base_path / "c2c"
    group_path = base_path / "group"
    dataline_path = base_path / "dataline"

    enabled = (
        {'c2c', 'group', 'dataline'}
        if conversation_types is None else conversation_types
    )
    for conversation_type, path in (
        ('c2c', c2c_path),
        ('group', group_path),
        ('dataline', dataline_path),
    ):
        if conversation_type in enabled:
            path.mkdir(parents=True, exist_ok=True)

    return c2c_path, group_path, dataline_path


def iter_parsed_messages(
    query,
    parse_message,
    batch_size: int,
    conversation_name: str = '',
):
    """分批读取 ORM 行并逐条解析，避免整个会话常驻内存。"""
    with ConversationReferenceResolver(
        query, conversation_name, batch_size
    ) as reference_resolver:
        for row in query.yield_per(batch_size):
            yield reference_resolver.resolve(parse_message(row))


def export_query(
    query,
    parse_message,
    meta: dict,
    members: list,
    output_formats: list[str],
    output_dir: Path,
    output_name: str,
    conversation_id: str,
    config: dict,
):
    """将查询导出为指定格式；纯流式格式不物化消息列表。"""
    exporters = []
    output_stem = conversation_output_stem(output_name, conversation_id)
    for format_name in output_formats:
        exporter_cls = EXPORTER_MAP.get(format_name)
        if not exporter_cls:
            logging.warning(f"未知的导出格式: {format_name}")
            continue
        extension = exporter_cls(output_dir, config).get_file_extension()
        output_path = output_dir / f"{output_stem}{extension}"
        exporters.append((exporter_cls(output_path, config), output_path))

    batch_size = max(1, int(config.get(
        'stream_batch_size', DEFAULT_STREAM_BATCH_SIZE
    )))
    incremental_exporters = [
        (exporter, output_path)
        for exporter, output_path in exporters
        if exporter.streams_messages
        and getattr(exporter, 'supports_incremental_messages', False)
    ]
    buffered_exporters = [
        (exporter, output_path)
        for exporter, output_path in exporters
        if not exporter.streams_messages
    ]
    legacy_streaming_exporters = [
        (exporter, output_path)
        for exporter, output_path in exporters
        if exporter.streams_messages
        and not getattr(exporter, 'supports_incremental_messages', False)
    ]

    materialized_messages = [] if buffered_exporters else None
    started_exporters = []
    try:
        for exporter, _ in incremental_exporters:
            started_exporters.append(exporter)
            exporter.start_stream(meta, members)
        if incremental_exporters or buffered_exporters:
            for message in iter_parsed_messages(
                query, parse_message, batch_size, output_name
            ):
                for exporter, _ in incremental_exporters:
                    exporter.write_message(message)
                if materialized_messages is not None:
                    materialized_messages.append(message)
        for exporter, output_path in incremental_exporters:
            exporter.finish_stream()
            logging.info(f"  导出完成: {output_path.name}")
    except Exception:
        for exporter in started_exporters:
            exporter.abort_stream()
        raise

    for exporter, output_path in buffered_exporters:
        exporter.export(meta, members, materialized_messages)
        logging.info(f"  导出完成: {output_path.name}")

    for exporter, output_path in legacy_streaming_exporters:
        messages = iter_parsed_messages(
            query, parse_message, batch_size, output_name
        )
        exporter.export(meta, members, messages)
        logging.info(f"  导出完成: {output_path.name}")


def export_c2c_conversation(
    parser: MessageParser,
    dbman: DatabaseManager,
    uid: str,
    query,
    output_formats: list[str],
    output_dir: Path,
    config: dict
):
    """导出单个私聊对话

    Args:
        parser: 消息解析器
        dbman: 数据库管理器
        uid: 对方 UID
        query: 消息查询对象
        output_formats: 导出格式列表
        output_dir: 输出目录
        config: 配置字典
    """
    # 获取对话信息
    profile = dbman.profile_info(uid)
    if profile:
        conversation_name = profile.remark or profile.nickname or str(profile.qq_num)
    else:
        # 如果找不到 profile，尝试从第一条消息获取
        first_msg = query.first()
        if first_msg and first_msg.mapping:
            conversation_name = str(first_msg.mapping.qq_num)
        elif first_msg:
            conversation_name = str(first_msg.interlocutor_num)
        else:
            conversation_name = uid

    logging.info(f"开始导出私聊: {conversation_name}")

    # 获取成员信息（私聊：我 + 对方）
    members = []

    # 对方
    other_member = parser.get_c2c_member(uid)
    if other_member:
        members.append(other_member)

    # 我（当前登录账号）
    self_member = parser.get_self_member()
    if self_member and (not other_member or self_member.platform_id != other_member.platform_id):
        members.append(self_member)

    # 构建 meta
    meta = {
        'name': conversation_name,
        'platform': 'qq',
        'type': 'private'
    }
    if self_member:
        meta['ownerId'] = self_member.platform_id

    export_query(
        query, parser.parse_c2c_message, meta, members, output_formats,
        output_dir, conversation_name, uid, config,
    )


def export_group_conversation(
    parser: MessageParser,
    dbman: DatabaseManager,
    group_num: int,
    query,
    output_formats: list[str],
    output_dir: Path,
    config: dict
):
    """导出单个群聊对话

    Args:
        parser: 消息解析器
        dbman: 数据库管理器
        group_num: 群号
        query: 消息查询对象
        output_formats: 导出格式列表
        output_dir: 输出目录
        config: 配置字典
    """
    # 获取群信息
    group_info = dbman.group_info(group_num)
    if group_info:
        conversation_name = group_info.remark or group_info.name or str(group_num)
        group_id = str(group_num)
    else:
        conversation_name = str(group_num)
        group_id = str(group_num)

    logging.info(f"开始导出群聊: {conversation_name}")

    # 只收集本次实际发送者，并补入群主和当前账号。
    owner_uid = dbman.group_owner_uid(group_num)
    members = parser.get_group_conversation_members(
        group_num, query, owner_uid
    )

    # 获取当前账号信息（用于判断"我"）
    self_member = parser.get_self_member()

    # 构建 meta
    meta = {
        'name': conversation_name,
        'platform': 'qq',
        'type': 'group',
        'groupId': group_id
    }
    group_avatar = public_group_avatar_url(group_num)
    if group_avatar:
        meta['groupAvatar'] = group_avatar
    if self_member:
        meta['ownerId'] = self_member.platform_id

    export_query(
        query, parser.parse_group_message, meta, members, output_formats,
        output_dir, conversation_name, str(group_num), config,
    )


def export_dataline_conversation(
    parser: MessageParser,
    partition_uid: str,
    query,
    output_formats: list[str],
    output_dir: Path,
    config: dict,
    owner_id: str,
):
    """导出一个数据线（我的手机/电脑/平板）会话。"""
    model = query.column_descriptions[0]['entity']
    sender_rows = list(query.with_entities(
        model.sender_uid, model.sender_num
    ).distinct())
    conversation_name = dataline_conversation_name(
        (row.sender_uid for row in sender_rows),
        owner_id,
        partition_uid,
    )
    logging.info(f"开始导出数据线: {conversation_name}")

    members = parser.get_dataline_members(sender_rows, owner_id)
    meta = {
        'name': conversation_name,
        'platform': 'qq',
        'type': 'private',
        'ownerId': owner_id,
    }

    export_query(
        query, parser.parse_dataline_message, meta, members, output_formats,
        output_dir, conversation_name, partition_uid, config,
    )


def main():
    """主程序"""
    if len(argv) < 2:
        print("用法: python main.py <config.toml>")
        return

    # 加载配置
    config_path = Path(argv[1])
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    # 数据库路径
    db_path = Path(config["db_path"])

    # 输出路径
    if not config.get("output_path"):
        output_path = db_path.parent / "output"
    else:
        output_path = Path(config["output_path"])

    configured_types = config.get(
        'conversation_types', ['c2c', 'group', 'dataline']
    )
    if isinstance(configured_types, str):
        configured_types = [configured_types]
    conversation_types = {
        str(conversation_type).lower()
        for conversation_type in configured_types
    }

    # 创建输出目录
    c2c_path, group_path, dataline_path = create_output_dirs(
        output_path, conversation_types
    )

    # 过滤器
    c2c_filters = config.get("c2c_filters", [])
    group_filters = config.get("group_filters", [])

    # 导出格式
    output_formats = config.get("output_format", ["chatlab_json"])

    # 初始化数据库管理器
    logging.info("连接数据库...")
    dbman = DatabaseManager(db_path)

    # 初始化解析器
    parser = MessageParser(dbman)

    # 获取查询
    c2c_queries = (
        dbman.c2c_messages(c2c_filters)
        if 'c2c' in conversation_types else {}
    )
    group_queries = (
        dbman.group_messages(group_filters)
        if 'group' in conversation_types else {}
    )
    dataline_owner_id = resolve_dataline_owner_id(
        config.get('dataline_owner')
    )
    dataline_queries = (
        dbman.dataline_messages()
        if 'dataline' in conversation_types else {}
    )

    # 导出私聊
    if c2c_queries:
        logging.info(f"找到 {len(c2c_queries)} 个私聊对话")
        for uid, query in tqdm(c2c_queries.items(), desc="导出私聊", unit="个"):
            try:
                export_c2c_conversation(
                    parser, dbman, uid, query,
                    output_formats, c2c_path, config
                )
            except Exception as e:
                logging.error(f"导出私聊 {uid} 失败: {e}", exc_info=True)

    # 导出群聊
    if group_queries:
        logging.info(f"找到 {len(group_queries)} 个群聊")
        for group_num, query in tqdm(group_queries.items(), desc="导出群聊", unit="个"):
            try:
                export_group_conversation(
                    parser, dbman, group_num, query,
                    output_formats, group_path, config
                )
            except Exception as e:
                logging.error(f"导出群聊 {group_num} 失败: {e}", exc_info=True)

    # 导出跨设备同步消息
    if dataline_queries:
        logging.info(f"找到 {len(dataline_queries)} 个数据线会话")
        for uid, query in tqdm(
            dataline_queries.items(), desc="导出数据线", unit="个"
        ):
            try:
                export_dataline_conversation(
                    parser, uid, query,
                    output_formats, dataline_path, config,
                    dataline_owner_id,
                )
            except Exception as e:
                logging.error(f"导出数据线 {uid} 失败: {e}", exc_info=True)

    logging.info("导出完成！")


if __name__ == '__main__':
    main()
