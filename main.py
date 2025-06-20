import argparse
import logging
from pathlib import Path

from tqdm import tqdm

import db
from export import base_elements
from export.json_exporter import C2cJsonExporter, GroupJsonExporter
from export.txt_exporter import C2cTxtExporter, GroupTxtExporter

parser = argparse.ArgumentParser(description="读取并导出解密后的QQNT数据库中的聊天记录")

parser.add_argument("db_path", type=str, help="解密后的数据库目录路径")
parser.add_argument("--c2c", nargs="*", type=int, help="需要输出的私聊消息的QQ号列表，默认导出全部")
parser.add_argument("--group", nargs="*", type=int, help="需要输出的群聊消息的群号列表，默认导出全部")
parser.add_argument(
    "--output_path", type=str, default=None, help="导出的路径，默认为数据库上级目录"
)
parser.add_argument("--pic_path", type=str, default="", help="chatpic目录路径，默认为空")
parser.add_argument(
    "--output_types",
    "-o",
    default=["txt"],
    nargs="+",
    choices=["txt", "json"],
    help="需要导出的文件格式，默认txt",
)


logging.basicConfig(
    level=logging.INFO,  # 设置默认日志级别
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

exporter_map = {
    "txt": {"c2c": C2cTxtExporter, "group": GroupTxtExporter},
    "json": {"c2c": C2cJsonExporter, "group": GroupJsonExporter},
}


def output_path(path):
    c2c_path = path / "output" / "c2c"
    group_path = path / "output" / "group"

    if not c2c_path.exists():
        c2c_path.mkdir(parents=True)
    if not group_path.exists():
        group_path.mkdir(parents=True)

    return c2c_path, group_path


def run_single(task_type, query, Exporter, path):
    logging.info(f"开始读取{task_type}消息")
    logging.info(f"成功读取{query.count()}条{task_type}消息")

    logging.info(f"开始解析并写入{task_type}消息")
    for message in tqdm(query.all()):
        exporter = Exporter(message)
        exporter.write(output_path=path)

    logging.info(f"成功解析并写入{task_type}消息")


def main():
    args = parser.parse_args()
    pic_path = Path(args.pic_path)
    base_elements.pic_path = pic_path
    db_path = Path(args.db_path)

    if args.output_path is None:
        args.output_path = Path(db_path / "..")
    else:
        args.output_path = Path(args.output_path)

    c2c_path, group_path = output_path(args.output_path)

    dbman = db.DatabaseManager(db_path)

    c2c_filters = args.c2c
    group_filters = args.group

    c2c_query = dbman.c2c_messages(c2c_filters)
    group_query = dbman.group_messages(group_filters)

    for output_type in args.output_types:
        c2c_exporter = exporter_map[output_type]["c2c"]
        group_exporter = exporter_map[output_type]["group"]

        run_single("私聊", c2c_query, c2c_exporter, c2c_path)
        run_single("群聊", group_query, group_exporter, group_path)

        logging.info(f"成功导出{output_type}格式")


if __name__ == '__main__':
    main()
