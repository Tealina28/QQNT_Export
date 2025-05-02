import logging
from pathlib import Path
from sys import argv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tqdm import tqdm

import c2c

logging.basicConfig(
    level=logging.INFO,  # 设置默认日志级别
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

def output_path(db_path):
    c2c_path = db_path / ".." / ".." / "output" / "c2c"
    group_path = db_path / ".." / ".." / "output" / "group"

    if not c2c_path.exists():
        c2c_path.mkdir(parents=True)
    if not group_path.exists():
        group_path.mkdir(parents=True)

    return c2c_path, group_path

def main():
    db_path = Path(argv[1]) / "nt_msg.db"
    c2c_path, group_path = output_path(db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    logging.info("成功连接数据库")

    logging.info("开始读取私聊消息")
    c2c_messages = c2c.read_messages(session)
    logging.info(f"成功读取{len(c2c_messages)}条私聊消息")

    logging.info("开始解析并写入私聊消息")
    for message in tqdm(c2c_messages):
        message.parse()
        message.write(c2c_path)


if __name__ == '__main__':
    main()
