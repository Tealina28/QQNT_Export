"""
QQNT Export - 重构版

解析和导出解耦的 QQNT 聊天记录导出工具。
"""

import logging
import tomllib
from pathlib import Path
from sys import argv

from db import DatabaseManager
from parser import MessageParser
from exporters import EXPORTER_MAP

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)


def sanitize_filename(filename) -> str:
    """清理文件名中的非法字符"""
    import re
    illegal_chars = r'[<>:"/\\|?*]'
    if isinstance(filename, int):
        return str(filename)
    return re.sub(illegal_chars, '_', str(filename))


def create_output_dirs(base_path: Path) -> tuple[Path, Path]:
    """创建输出目录结构

    Returns:
        (c2c_path, group_path) 元组
    """
    c2c_path = base_path / "c2c"
    group_path = base_path / "group"

    c2c_path.mkdir(parents=True, exist_ok=True)
    group_path.mkdir(parents=True, exist_ok=True)

    return c2c_path, group_path


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

    # 解析消息
    messages = [parser.parse_c2c_message(msg) for msg in query.all()]

    # 获取成员信息（私聊：我 + 对方）
    members = []

    # 对方
    other_member = parser.get_c2c_member(uid)
    if other_member:
        members.append(other_member)

    # TODO: 添加"我"的信息（需要从配置或数据库获取当前用户信息）

    # 构建 meta
    meta = {
        'name': conversation_name,
        'platform': 'qq',
        'type': 'private'
    }

    # 导出
    for format_name in output_formats:
        exporter_cls = EXPORTER_MAP.get(format_name)
        if not exporter_cls:
            logging.warning(f"未知的导出格式: {format_name}")
            continue

        # 构建输出文件路径
        extension = exporter_cls(output_dir, config).get_file_extension()
        output_path = output_dir / f"{sanitize_filename(conversation_name)}{extension}"

        # 导出
        exporter = exporter_cls(output_path, config)
        exporter.export(meta, members, messages)

        logging.info(f"  导出完成: {output_path.name}")


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

    # 解析消息
    messages = [parser.parse_group_message(msg) for msg in query.all()]

    # 获取群成员信息
    members = parser.get_all_group_members(group_num)

    # 构建 meta
    meta = {
        'name': conversation_name,
        'platform': 'qq',
        'type': 'group',
        'groupId': group_id
    }

    # 导出
    for format_name in output_formats:
        exporter_cls = EXPORTER_MAP.get(format_name)
        if not exporter_cls:
            logging.warning(f"未知的导出格式: {format_name}")
            continue

        # 构建输出文件路径
        extension = exporter_cls(output_dir, config).get_file_extension()
        output_path = output_dir / f"{sanitize_filename(conversation_name)}{extension}"

        # 导出
        exporter = exporter_cls(output_path, config)
        exporter.export(meta, members, messages)

        logging.info(f"  导出完成: {output_path.name}")


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

    # 创建输出目录
    c2c_path, group_path = create_output_dirs(output_path)

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
    c2c_queries = dbman.c2c_messages(c2c_filters)
    group_queries = dbman.group_messages(group_filters)

    # 导出私聊
    if c2c_queries:
        logging.info(f"找到 {len(c2c_queries)} 个私聊对话")
        for uid, query in c2c_queries.items():
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
        for group_num, query in group_queries.items():
            try:
                export_group_conversation(
                    parser, dbman, group_num, query,
                    output_formats, group_path, config
                )
            except Exception as e:
                logging.error(f"导出群聊 {group_num} 失败: {e}", exc_info=True)

    logging.info("导出完成！")


if __name__ == '__main__':
    main()
