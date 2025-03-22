from c2c_message import Message
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
def write(output_path,interlocutor_num,messages):
        txt_path = output_path / f"{interlocutor_num}.txt"
        for message in messages:
            message.write(txt_path)

        print(f"输出了{len(messages)}条消息到{txt_path}")

def c2c(db_path,cursor,mapping):
    output_path = db_path / ".." / ".." / "output" / "c2c"

    if not output_path.exists():
        output_path.mkdir(parents=True)
        print(f"创建了输出文件夹{output_path}")

    all_messages = {}
    print("正在读取消息")
    for row in cursor.execute('SELECT "40020","40021","40050","40800","40030","40033" FROM c2c_msg_table ORDER BY "40050"'):
        sender_num = mapping.get(row[0],row[5])
        interlocutor_num = mapping.get(row[1],row[4])
        # 这么做是因为num或uid有时为空，但同时为空的情况较少
        if row[3]:
            message = Message(row[2],row[3],sender_num,interlocutor_num)
            message.parse()
        else:
            continue

        if interlocutor_num not in all_messages:
            all_messages[interlocutor_num] = []
        all_messages[interlocutor_num].append(message)

    print("正在输出消息")
    with ThreadPoolExecutor(16) as executor:
        for interlocutor_num,messages in all_messages.items():
            executor.submit(write,output_path,interlocutor_num,messages)
