from pathlib import Path
import sqlite3
import sys

from c2c import c2c
from group import group

def load_mapping(cursor):
    mapping = {}
    result = cursor.execute('SELECT "48902","1002" FROM nt_uid_mapping_table')
    for row in result:
        mapping[row[0]] = row[1]

    return mapping
def main():
    db_path = Path(sys.argv[1]) / "nt_msg.db"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("正在加载uid索引")
    mapping =  load_mapping(cursor)

    c2c(db_path,cursor,mapping)
    group(db_path,cursor,mapping)

    conn.close()


if __name__ == "__main__":
    main()