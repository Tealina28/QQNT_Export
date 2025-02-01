import sqlite3
import qq_msg_pb2
import datetime
from re import search, findall
from json import loads, JSONDecodeError
import os


def get_message_from_raw(interlocutor_num, sender_num, time_stamp, raw):
    """解析原始消息数据"""
    messages = qq_msg_pb2.Message()
    messages.ParseFromString(raw)
    return messages, interlocutor_num, sender_num, time_stamp


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


import os
import sqlite3
from datetime import datetime

def decode(path):
    """
    主函数，负责解码数据库中的消息并输出到文件
    """

    # 创建输出文件夹
    output_dir = os.path.join(os.path.dirname(path), "outputs")  # 修改：将输出文件夹放在path的上级目录
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
    except OSError as e:
        print(f"创建输出文件夹失败: {e}")
        return

    # 连接数据库
    try:
        conn = sqlite3.connect(os.path.join(path, "nt_msg.db"))
        c = conn.cursor()

        # 主程序
        interlocutor_messages = {}  # 用于存储每个interlocutor_num的消息
        cursor = c.execute("SELECT * FROM c2c_msg_table")
        for row in cursor:
            if row[17] is None:
                continue
            data = row[17]
            interlocutor_num = row[31]  # 提取 interlocutor_num
            sender_num = row[32]  # 提取 sender_num
            time_stamp = row[13]  # 提取 time_stamp
            try:
                messages, interlocutor_num, sender_num, time_stamp = get_message_from_raw(interlocutor_num, sender_num, time_stamp, data)
                formatted_message = get_message_from_single(messages, interlocutor_num, sender_num, time_stamp)
                if interlocutor_num not in interlocutor_messages:
                    interlocutor_messages[interlocutor_num] = []
                interlocutor_messages[interlocutor_num].append((time_stamp, formatted_message))  # 修改：存储时间戳和格式化消息
            except Exception as e:
                print(f"处理消息时出错: {e}")

        # 按时间戳排序并写入文件
        for interlocutor_num, messages in interlocutor_messages.items():
            # 按时间戳排序
            sorted_messages = sorted(messages, key=lambda x: x[0])  # 修改：使用时间戳排序
            try:
                with open(os.path.join(output_dir, f"{interlocutor_num}.txt"), "a", encoding="utf-8") as interlocutor_file:
                    for time, message in sorted_messages:
                        # 将时间戳转换为可读时间并格式化输出
                        readable_time = datetime.fromtimestamp(time).strftime('%Y-%m-%d %H:%M:%S')
                        interlocutor_file.write(f"{readable_time}-{message}\n")
            except IOError as e:
                print(f"写入文件时出错: {e}")

    except sqlite3.Error as e:
        print(f"数据库操作出错: {e}")
    finally:
        if conn:
            conn.close()



def get_message_from_single(messages, interlocutor_num, sender_num, time_stamp):
    """解析单条消息"""
    try:
        formatted_messages = []  # 创建一个列表来存储所有消息的格式化字符串
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
        for message in messages.messages:
            message_type = message.messageType
            message_content = message_type_handlers.get(message_type, lambda _: "[未知消息类型]")(message)

            # 提取 interlocutorNum, senderNum, timeStamp
            direction = "收" if interlocutor_num == sender_num else "发"

            # 将提取的信息与消息内容一起存储在列表中
            formatted_messages.append((time_stamp, direction, message_content))  # 将格式化字符串添加到列表中

        # 按时间戳排序
        formatted_messages.sort(key=lambda x: x[0])

        # 返回所有消息的格式化字符串，用换行符分隔
        return "\n".join(f"{direction}-{content}" for _, direction, content in formatted_messages)

    except Exception as e:
        print(f"解析消息时出错: {e}")
        return ""

if __name__ == "__main__":
    decode(path)