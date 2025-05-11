import logging
import argparse
from pathlib import Path
from tqdm import tqdm

import db

parser = argparse.ArgumentParser(description="读取并导出解密后的QQNT数据库中的聊天记录")

parser.add_argument("path", type=str, help="解密后的数据库目录路径")
parser.add_argument("--c2c", nargs="*", type=int, help="需要输出的私聊消息的QQ号列表")
parser.add_argument("--group", nargs="*", type=int, help="需要输出的群聊消息的群号列表")


logging.basicConfig(
    level=logging.INFO,  # 设置默认日志级别
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)


def output_path(db_path):
    c2c_path = db_path / ".." / "output" / "c2c"
    group_path = db_path / ".." / "output" / "group"

    if not c2c_path.exists():
        c2c_path.mkdir(parents=True)
    if not group_path.exists():
        group_path.mkdir(parents=True)

    return c2c_path, group_path


def run_single(query, task_type, path):
    logging.info(f"开始读取{task_type}消息")
    logging.info(f"成功读取{query.count()}条{task_type}消息")

    logging.info(f"开始解析并写入{task_type}消息")
    for message in tqdm(query.all()):
        message.parse()
        message.write(path)
    logging.info(f"成功解析并写入{task_type}消息")

def main():
    args = parser.parse_args()

    db_path = Path(args.path)
    c2c_path, group_path = output_path(db_path)

    dbman = db.DatabaseManager(db_path)

    c2c_filters = args.c2c
    group_filters = args.group

    c2c_query = dbman.c2c_messages(c2c_filters)
    group_query = dbman.group_messages(group_filters)

    run_single(c2c_query, "私聊", c2c_path)
    run_single(group_query, "群聊", group_path)

if __name__ == '__main__':
    main()
