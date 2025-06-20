import logging
import tomllib

from sys import argv
from pathlib import Path
from tqdm import tqdm

import db
from export import base_elements
from export.json_exporter import C2cJsonExporter, GroupJsonExporter
from export.txt_exporter import C2cTxtExporter, GroupTxtExporter

logging.basicConfig(
    level=logging.INFO,  # 设置默认日志级别
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

exporter_map = {
    "txt": {"c2c": C2cTxtExporter, "group": GroupTxtExporter},
    "json": {"c2c": C2cJsonExporter, "group": GroupJsonExporter},
}


def mk_output_path(path):
    c2c_path = path / "c2c"
    group_path = path / "group"

    if not c2c_path.exists():
        c2c_path.mkdir(parents=True)
    if not group_path.exists():
        group_path.mkdir(parents=True)

    return c2c_path, group_path


def run_single(task_type, query, Exporter, path):
    logging.info(f"开始读取{task_type}消息")
    logging.info(f"成功读取{query.count()}条{task_type}消息")

    logging.info(f"开始解析并写入{task_type}消息")
    for message in tqdm(query.all()):
        exporter = Exporter(message)
        exporter.write(output_path=path)

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

    dbman = db.DatabaseManager(db_path)

    c2c_filters = config["c2c_filters"]
    group_filters = config["group_filters"]

    c2c_query = dbman.c2c_messages(c2c_filters)
    group_query = dbman.group_messages(group_filters)

    for output_type in config["output_format"]:
        c2c_exporter = exporter_map[output_type]["c2c"]
        group_exporter = exporter_map[output_type]["group"]

        run_single("私聊", c2c_query, c2c_exporter, c2c_path)
        run_single("群聊", group_query, group_exporter, group_path)

        logging.info(f"成功导出{output_type}格式")


if __name__ == '__main__':
    main()
