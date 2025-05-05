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


def main():

    db_path = Path(argv[1])
    c2c_path, group_path = output_path(db_path)

    dbman = db.DatabaseManager(db_path)

    logging.info("开始读取私聊消息")
    c2c_messages = dbman.c2c_messages()
    logging.info(f"成功读取{c2c_messages.count()}条私聊消息")

    logging.info("开始读取群聊消息")
    group_messages = dbman.group_messages()
    logging.info(f"成功读取{group_messages.count()}条群聊消息")

    logging.info("开始解析并写入私聊消息")
    for message in tqdm(c2c_messages.all()):
        message.parse()
        message.write(c2c_path)
    logging.info("成功解析并写入私聊消息")

    logging.info("开始解析并写入群聊消息")
    for message in tqdm(group_messages.all()):
        message.parse()
        message.write(group_path)
    logging.info("成功解析并写入群聊消息")

if __name__ == '__main__':
    main()
