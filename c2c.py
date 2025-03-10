from c2c_message import Message
from pathlib import Path
import sqlite3

def load_mapping(cursor):
    mapping = {}
    result = cursor.execute('SELECT "48902","1002" FROM nt_uid_mapping_table')
    for row in result:
        mapping[row[0]] = row[1]

    return mapping

def c2c(path):
    path = Path(path)
    db_path = path / "nt_msg.db"
    output_path = path / ".." / "output" / "c2c"

    if not output_path.exists():
        output_path.mkdir(parents=True)
        print(f"创建了输出文件夹{output_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("正在加载uid索引")
    mapping = load_mapping(cursor)

    all_messages = {}
    print("正在读取消息")
    for row in cursor.execute('SELECT "40020","40021","40050","40800","40030","40033" FROM c2c_msg_table ORDER BY "40050"'): # 后续改为仅读取需要的列
        sender_uin = mapping.get(row[0],row[5])
        interlocutor_uin = mapping.get(row[1],row[4])
        # 这么做是因为uid或uin有时为空，但同时为空的情况较少
        if row[3]:
            message = Message(row[2],row[3],sender_uin,interlocutor_uin)
            message.parse()
        else:
            continue

        if interlocutor_uin not in all_messages:
            all_messages[interlocutor_uin] = []
        all_messages[interlocutor_uin].append(message)

    print("输出消息中")
    for interlocutor_uin,messages in all_messages.items():
        txt_path = output_path / f"{interlocutor_uin}.txt"
        for message in messages:
            message.write(txt_path)

        print(f"输出了{len(messages)}条消息到{txt_path}")

    conn.close()