from message import C2cMessage


def parse(param):
    time_stamp, raw, sender_num, interlocutor_num = param
    message = C2cMessage(time_stamp, raw, sender_num, interlocutor_num)
    message.parse()

    return message

def read(cursor, mapping):
    params = [
        (row[4], row[5], mapping.get(row[0], {}).get("num", row[3]), mapping.get(row[1], {}).get("num", row[2]))
        for row in cursor.execute('SELECT "40020","40021","40030","40033","40050","40800" FROM c2c_msg_table ORDER BY "40050"')
        if row[5]
    ]

    return params
