from group_message import Message
from concurrent.futures import ThreadPoolExecutor

def parse(param):
    time_stamp, raw, sender_num, group_num = param
    message = Message(time_stamp, raw, sender_num, group_num)
    message.parse()

    return message


def read(cursor, mapping):

    params = [
        (row[4], row[6], mapping.get(row[2],None), row[3])
        for row in cursor.execute('SELECT "40011","40012","40020","40021","40050","40090","40800" FROM group_msg_table ORDER BY "40050"')
        if row[6]
    ]

    return params
