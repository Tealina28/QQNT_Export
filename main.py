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


def load_profile(cursor):
    result = cursor.execute('SELECT "1002","20002","20009","1000" FROM profile_info_v6')
    mapping = {row[3]: {"num": row[0], "nickname": row[1], "remark_name": row[2], "uid": row[3]} for row in result}

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

    path = Path(argv[1])
    c2c_path, group_path = output_path(path / "nt_msg.db")
    
    msg_coon = sqlite3.connect(path / "nt_msg.db")
    msg_cursor = msg_coon.cursor()

    profile_coon = sqlite3.connect(path / "profile_info.db")
    profile_cursor = profile_coon.cursor()

    print("开始读取用户数据")
    mapping = load_profile(profile_cursor)
    profile_coon.close()
    print("完成读取用户数据")

    print("开始读取消息")
    c2c_params = c2c.read(msg_cursor, mapping)
    group_params = group.read(msg_cursor, mapping)
    print("完成读取消息")

    print("开始解析消息")
    c2c_messages = threading_parse(c2c.parse, c2c_params, parse_thread_num)
    group_messages = threading_parse(group.parse, group_params, parse_thread_num)
    print("完成解析消息")

    print("开始输出消息")
    threading_write(write, c2c_path, c2c_messages, write_thread_num)
    threading_write(write, group_path, group_messages, write_thread_num)
    print("完成输出消息")

    msg_coon.close()


if __name__ == "__main__":
    main()