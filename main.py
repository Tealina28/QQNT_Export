import logging
from pathlib import Path
from sys import argv

import sqlite3
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

    # c2c_path = Path(".") / "output" / "c2c"
    # group_path = Path(".") / "output" / "group"
    if not c2c_path.exists():
        c2c_path.mkdir(parents=True)
    if not group_path.exists():
        group_path.mkdir(parents=True)

    return c2c_path, group_path

def init_db(db_path: Path | str):
    db_conn = sqlite3.connect(db_path)
    db_conn.execute("PRAGMA journal_mode=WAL;")
    cursor = db_conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time_stamp INTEGER,
            time TEXT,
            sender_qq TEXT,
            interlocutor_qq TEXT,
            types TEXT,
            contents JSON,
            direction_str TEXT CHECK(direction_str IN ('收', '发', '转发', '未知')),
            direction INTEGER 
            );
    """)

    return db_conn, cursor


def run_single(get_message, task_type, path, write_db: bool = False):
    logging.info(f"开始读取{task_type}消息")
    messages = get_message()
    logging.info(f"成功读取{messages.count()}条{task_type}消息")

    logging.info(f"开始解析并写入{task_type}消息")
    for message in tqdm(messages.all()):
        message.parse()
        message.write(path)

    if write_db:
        # ONLY SUPPORT -> c2c messages <-
        db_connections = {}
        msgs = {}
        logging.info("已启用写入数据库，正在初始化数据库")

        # preprocess messages
        for message in message.all():
            message.parse()
            if message.interlocutor_num not in db_connections.keys():
                db_conn, cursor = init_db(
                    path
                    / f"{message.mapping.qq_num if message.mapping else message.interlocutor_num}.db"
                )
                db_connections[message.interlocutor_num] = db_conn, cursor
                msgs[message.interlocutor_num] = []

            msgs[message.interlocutor_num].append(message.write_db())

        # write to db
        for interlocutor_num in tqdm(msgs.keys()):
            db_conn, cursor = db_connections[interlocutor_num]
            cursor.executemany(
                "INSERT INTO messages (time_stamp, time, sender_qq, interlocutor_qq, types, contents, direction_str, direction) VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                msgs[interlocutor_num],
            )
            db_conn.commit()
            db_conn.close()
            cursor.close()

    logging.info(f"成功解析并写入{task_type}消息")

def main(write_db: bool = False):

    db_path = Path(argv[1])
    c2c_path, group_path = output_path(db_path)

    dbman = db.DatabaseManager(db_path)

    run_single(dbman.c2c_messages, "私聊", c2c_path, write_db)
    run_single(dbman.group_messages, "群聊", group_path)

if __name__ == '__main__':
    main(True)
