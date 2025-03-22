from c2c_message import Message
from concurrent.futures import ThreadPoolExecutor

def parse(param):
    time_stamp, raw, sender_num, interlocutor_num = param
    message = Message(time_stamp, raw, sender_num, interlocutor_num)
    message.parse()
    return message

def write(output_path, interlocutor_num, messages):
    txt_path = output_path / f"{interlocutor_num}.txt"
    for message in messages:
        message.write(txt_path)
    print(f"输出了{len(messages)}条消息到{txt_path}")

def c2c(db_path, cursor, mapping):
    output_path = db_path / ".." / ".." / "output" / "c2c"

    if not output_path.exists():
        output_path.mkdir(parents=True)
        print(f"创建了输出文件夹{output_path}")

    all_messages = {}
    print("正在读取私聊消息")

    params = (
        (row[2], row[3], mapping.get(row[0], row[5]), mapping.get(row[1], row[4]))
        for row in cursor.execute('SELECT "40020","40021","40050","40800","40030","40033" FROM c2c_msg_table ORDER BY "40050"')
        if row[3]
    )

    with ThreadPoolExecutor(16) as executor:
        for message in executor.map(parse, params):
            if message.interlocutor_num not in all_messages:
                all_messages[message.interlocutor_num] = []
            all_messages[message.interlocutor_num].append(message)

    print("正在输出私聊消息")
    with ThreadPoolExecutor(16) as executor:
        for interlocutor_num, messages in all_messages.items():
            executor.submit(write, output_path, interlocutor_num, messages)
