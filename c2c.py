import os
import sqlite3
from datetime import datetime
from json import loads, JSONDecodeError
from re import search, findall

import c2c_msg_pb2


# def get_message_from_raw(raw):
#     """解析原始消息数据"""
#     messages = c2c_msg_pb2.Message()
#     messages.ParseFromString(raw)
#     return messages

def extract_txt(data):
    """解析提示消息的文本"""
    try:
        data_dict = loads(data)
        return ''.join(item['txt'] for item in data_dict['items'] if item['type'] in ['nor', 'url'])
    except JSONDecodeError:
        return ''.join(findall(r'txt="(.*?)"', data))


def get_message_text(message):
    """获取消息文本"""
    return f"[文本消息]{message.messageText}"


def get_image_message(message):
    """获取图片消息"""
    return f"[图片消息]{message.imageText}"


def get_file_message(message):
    """获取文件消息"""
    return f"[文件消息]{message.fileName}"


def get_emoji_message(message):
    """获取动画表情消息"""
    return f"[动画表情]{message.emojiText}"


def get_notice_message(message):
    """获取提示消息"""
    notice_info = message.noticeInfo or message.noticeInfo2
    if notice_info:
        return f"[提示消息]{extract_txt(notice_info)}"
    return "[提示消息]"


def get_application_message(message):
    """获取应用消息"""
    match = search(r"'desc':'(.*?)''", message.applicationMessage)
    if match:
        return f"[应用消息]{match.group(1)}"
    return "[应用消息]"


def get_call_message(message):
    """获取通话消息"""
    return f"[通话消息]{message.callText}"


def get_feed_message(message):
    """获取动态消息"""
    return f"[动态消息]{message.feedTitle}:{message.feedContent}({message.feedUrl})"


def get_content(raw):
    """解析消息内容"""
    contents = []
    Message = c2c_msg_pb2.Message()
    Message.ParseFromString(raw)
    for SingleMessage in Message.messages:
        try:
            message_type_handlers = {
                1: get_message_text,
                2: get_image_message,
                3: get_file_message,
                6: get_emoji_message,
                8: get_notice_message,
                10: get_application_message,
                21: get_call_message,
                26: get_feed_message
            }
            content = message_type_handlers.get(SingleMessage.messageType, lambda _: "[未知消息类型]")(SingleMessage)
            contents.append(content)
        except Exception as e:
            print(f"解析消息时出错: {e}")
        return contents


def sort_by_time(interlocutor_messages):
    """
    对消息列表进行排序，按照时间戳升序排列
    """
    for interlocutor_num, messages in interlocutor_messages.items():
        interlocutor_messages[interlocutor_num] = sorted(messages, key=lambda x: x[0])
    return interlocutor_messages


def write_to_file(sorted_interlocutor_messages, output_dir):
    for interlocutor_num, messages in sorted_interlocutor_messages.items():
        with open(os.path.join(output_dir, f"{interlocutor_num}.txt"), "w", encoding="utf-8") as file:
            for timestamp, sender_num, context in messages:
                readable_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
                file.write(f"{readable_time} {sender_num}: {context}\n")


def get_num_from_mapping(c2, index, uid, default_value):
    if uid in index:
        return index[uid]

    if uid:
        try:
            result = c2.execute('SELECT "1002" FROM nt_uid_mapping_table WHERE "48902" = ?', (uid,)).fetchone()
            if result:
                num = result[0]
                index[uid] = num
                return num
        except Exception as e:
            print(f"Database query failed for UID {uid}: {e}")
            return default_value
    return default_value

def decode_c2c(path):
    """
    主函数，负责解码数据库中的私聊消息并输出到文件
    """
    output_dir = os.path.join(os.path.dirname(path), "outputs", "c2c")
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print("创建输出文件夹成功")
    except OSError as e:
        print(f"创建输出文件夹失败: {e}")
        return

    try:
        conn = sqlite3.connect(os.path.join(path, "nt_msg.db"))
        c1 = conn.cursor()
        c2 = conn.cursor()
        c2c = c1.execute("SELECT * FROM c2c_msg_table")
        print("数据库连接成功")

        interlocutor_messages = {}
        mapping = {}
        print("正在读取数据库，请稍等...")
        for row in c2c:
            if row[17] is None:
                continue
            time_stamp = row[13]
            raw = row[17]
            sender_uid = row[8]
            interlocutor_uid = row[9]

            interlocutor_num = get_num_from_mapping(c2, mapping, interlocutor_uid, row[31])
            sender_num = get_num_from_mapping(c2, mapping, sender_uid, row[32])

            contents = get_content(raw)

            if interlocutor_num not in interlocutor_messages:
                interlocutor_messages[interlocutor_num] = []

            direction = "收" if sender_num == interlocutor_num else "发"
            for content in contents:
                interlocutor_messages[interlocutor_num].append((time_stamp, direction, content))

        print("正在排序消息，请稍等...")
        sorted_interlocutor_messages = sort_by_time(interlocutor_messages)
        print("正在输出消息，请稍等...")
        write_to_file(sorted_interlocutor_messages, output_dir)
        print(f"成功输出，输出的路径为{output_dir}")

    except sqlite3.Error as e:
        print(f"数据库操作出错: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    decode_c2c("E:/QEData/decrypt_1738471602")
