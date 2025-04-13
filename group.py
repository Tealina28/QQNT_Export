from message import GroupMessage


def parse(param):
    time_stamp, raw, sender_num, interlocutor_num, username, remark_name, name_card = param
    message = GroupMessage(time_stamp, raw, sender_num, interlocutor_num, username, remark_name, name_card)
    message.parse()

    return message


def read(cursor, mapping):

    params = [
        (row[7], row[10], mapping.get(row[2],{}).get("num", row[6]), row[3] or row[4] or row[5], mapping.get(row[2],{}).get("username", ""), mapping.get(row[2],{}).get("remark_name",row[9]), row[8])
        for row in cursor.execute('SELECT "40011","40012","40020","40021","40027","40030","40033","40050","40090","40093","40800" FROM group_msg_table ORDER BY "40050"')
        if row[10]
    ]

    return params
