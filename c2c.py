from message import C2cMessage

def parse(param):
    time_stamp, raw, sender_num, interlocutor_num, username, remark_name, mapping = param
    message = C2cMessage(time_stamp, raw, sender_num, interlocutor_num, username, remark_name, mapping=mapping)
    message.parse()
    return message

def read(cursor, mapping):
    params = [
        (row[4], row[6], mapping.get(row[0], {}).get("num", row[3]),
         mapping.get(row[1], {}).get("num", row[2]),
         mapping.get(row[1], {}).get("nickname", ""),
         mapping.get(row[1], {}).get("remark_name", row[5]),
         mapping)
        for row in cursor.execute('SELECT "40020","40021","40030","40033","40050","40093","40800" FROM c2c_msg_table ORDER BY "40050"')
        if row[6]
    ]
    return params
