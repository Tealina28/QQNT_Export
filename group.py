from group_message import Message
from concurrent.futures import ThreadPoolExecutor

def parse(param):
    time_stamp, raw, sender_num, group_num = param
    message = Message(time_stamp, raw, sender_num, group_num)
    message.parse()
    return message

def write(output_path, group_num, messages):
        txt_path = output_path / f"{group_num}.txt"
        for message in messages:
            message.write(txt_path)

        print(f"输出了{len(messages)}条消息到{txt_path}")

def group(db_path, cursor, mapping):
    output_path = db_path / ".." / ".." / "output" / "group"

    if not output_path.exists():
        output_path.mkdir(parents=True)
        print(f"创建了输出文件夹{output_path}")

    all_messages = {}
    print("正在读取群聊消息")

    params = (
        (row[4], row[6], mapping.get(row[2],None), row[3])
        for row in cursor.execute('SELECT "40011","40012","40020","40021","40050","40090","40800" FROM group_msg_table ORDER BY "40050"')
        if row[6]
    )

    with ThreadPoolExecutor(16) as executor:
        for message in executor.map(parse, params):
            if message.group_num not in all_messages:
                all_messages[message.group_num] = []
            all_messages[message.group_num].append(message)

    print("正在输出群聊消息")
    with ThreadPoolExecutor(16) as executor:
        for group_num, messages in all_messages.items():
            executor.submit(write, output_path, group_num, messages)
