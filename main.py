import logging
from pathlib import Path
from sys import argv

from tqdm import tqdm

import db

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


def run_single(get_message, task_type, path):
    logging.info(f"开始读取{task_type}消息")
    messages = get_message()
    logging.info(f"成功读取{messages.count()}条{task_type}消息")

    logging.info(f"开始解析并写入{task_type}消息")
    for message in tqdm(messages.all()):
        message.parse()
        message.write(path)
    logging.info(f"成功解析并写入{task_type}消息")

def main():

    db_path = Path(argv[1])
    c2c_path, group_path = output_path(db_path)

    dbman = db.DatabaseManager(db_path)

    run_single(dbman.c2c_messages, "私聊", c2c_path)
    run_single(dbman.group_messages, "群聊", group_path)

if __name__ == '__main__':
    main()
