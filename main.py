from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from sys import argv
import sqlite3

import c2c
import group

def output_path(db_path):
    c2c_path = db_path / ".." / ".." / "output" / "c2c"
    group_path = db_path / ".." / ".." / "output" / "group"

    if not c2c_path.exists():
        c2c_path.mkdir(parents=True)
    if not group_path.exists():
        group_path.mkdir(parents=True)

    return c2c_path, group_path


def load_mapping(cursor):
    result = cursor.execute('SELECT "48902","1002" FROM nt_uid_mapping_table')
    mapping = {row[0] : row[1] for row in result}

    return mapping


def threading_parse(parse, params,parse_thread_num):
    all_messages = {}
    with ThreadPoolExecutor(parse_thread_num) as executor:
        for message in executor.map(parse, params):
            if message.interlocutor_num not in all_messages:
                all_messages[message.interlocutor_num] = []
            all_messages[message.interlocutor_num].append(message)

    return all_messages


def write(output_path, interlocutor_num, messages):
    txt_path = output_path / f"{interlocutor_num}.txt"
    for message in messages:
        message.write(txt_path)
    print(f"输出了{len(messages)}条消息到{txt_path}")


def threading_write(write, output_path, all_messages, write_thread_num):
    with ThreadPoolExecutor(write_thread_num) as executor:
        for interlocutor_num, messages in all_messages.items():
            executor.submit(write, output_path, interlocutor_num, messages)


def main():
    parse_thread_num = 16
    write_thread_num = 16

    db_path = Path(argv[1]) / "nt_msg.db"
    c2c_path, group_path = output_path(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("开始读取uid索引")
    mapping =  load_mapping(cursor)
    print("完成读取uid索引")

    print("开始读取消息")
    c2c_params = c2c.read(cursor, mapping)
    group_params = group.read(cursor, mapping)
    print("完成读取消息")

    print("开始解析消息")
    c2c_messages = threading_parse(c2c.parse, c2c_params, parse_thread_num)
    group_messages = threading_parse(group.parse, group_params, parse_thread_num)
    print("完成解析消息")

    print("开始输出消息")
    threading_write(write, c2c_path, c2c_messages, write_thread_num)
    threading_write(write, group_path, group_messages, write_thread_num)
    print("完成输出消息")

    conn.close()


if __name__ == "__main__":
    main()