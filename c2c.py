from message import C2cMessage


def parse(param):
    time_stamp, raw, sender_num, interlocutor_num = param
    message = C2cMessage(time_stamp, raw, sender_num, interlocutor_num)
    message.parse()

    return message

def read(cursor, mapping):
    params = [
        (row[2], row[3], mapping.get(row[0], row[5]), mapping.get(row[1], row[4]))
        for row in cursor.execute('SELECT "40020","40021","40050","40800","40030","40033" FROM c2c_msg_table ORDER BY "40050"')
        if row[3]
    ]

    return params
