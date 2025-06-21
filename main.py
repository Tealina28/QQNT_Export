import logging
import tomllib

from sys import argv
from pathlib import Path

import db
from exporter import base_elements
from exporter.json import JsonExportManager
from exporter.txt import TxtExportManager

logging.basicConfig(
    level=logging.INFO,  # 设置默认日志级别
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

exporter_map = {
    "txt": TxtExportManager,
    "json": JsonExportManager,
}


def mk_output_path(path):
    c2c_path = path / "c2c"
    group_path = path / "group"

    if not c2c_path.exists():
        c2c_path.mkdir(parents=True)
    if not group_path.exists():
        group_path.mkdir(parents=True)

    return c2c_path, group_path


def run_single(task_type, queries, Exporter, path, dbman):
    logging.info(f"开始解析并写入{task_type}消息")
    Exporter(dbman,queries, path, task_type).process()

    logging.info(f"成功解析并写入{task_type}消息")


def main():
    config_path = Path(argv[1])
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    db_path = Path(config["db_path"])

    pic_path = Path(config["pic_path"])
    base_elements.pic_path = pic_path

    if not config["output_path"]:
        output_path = Path(db_path).parent / "output"
    else:
        output_path = Path(config["output_path"])

    c2c_path, group_path = mk_output_path(output_path)

    c2c_filters = config["c2c_filters"]
    group_filters = config["group_filters"]

    dbman = db.DatabaseManager(db_path)

    c2c_queries = dbman.c2c_messages(c2c_filters)
    group_queries = dbman.group_messages(group_filters)

    for output_type in config["output_format"]:
        c2c_exporter = exporter_map[output_type]
        group_exporter = exporter_map[output_type]

        run_single("c2c", c2c_queries, c2c_exporter, c2c_path, dbman)
        run_single("group", group_queries, group_exporter, group_path, dbman)

        logging.info(f"成功导出{output_type}格式")


if __name__ == '__main__':
    main()
