from collections import defaultdict

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.query import Query

__all__ = ["DatabaseManager"]


class DatabaseManager:
    _models = defaultdict(defaultdict)  # {db_id: {table_name: model}}
    _engines = {}  # {db_id: engine}
    _binds = {}  # {model: engine}

    @classmethod
    def register_model(cls, db_id: str) -> callable:
        def wrapper(model):
            cls._models[db_id][model.__tablename__] = model
            return model

        return wrapper

    def __new__(cls, db_path):
        for db_filename in cls._models.keys():
            db_file = db_path / f"{db_filename}.db"
            if db_file.exists():
                engine = create_engine(f"sqlite:///{db_file}")
                cls._engines[db_filename] = engine

                # 将该数据库下的所有模型绑定到对应的引擎
                for model in cls._models[db_filename].values():
                    cls._binds[model] = engine

        # 重新配置 session factory
        cls._session_factory = sessionmaker(binds=cls._binds)
        cls._session_factory.configure(binds=cls._binds)
        cls.session = cls._session_factory()

        return super(DatabaseManager, cls).__new__(cls)

    def __init__(self, db_path):
        pass

    def num_to_uid(self, num: int) -> str:
        model = self._models["nt_msg"]["nt_uid_mapping_table"]
        return self.session.query(model).filter_by(qq_num = num).first().uid

    def c2c_messages(self, filters):
        model = self._models["nt_msg"]["c2c_msg_table"]
        query = self.session.query(model)
        if filters:
            uids = [self.num_to_uid(num) for num in filters]
        else:
            uids = [row[0] for row in self.session.query(model.interlocutor_uid).distinct().all()]

        queries = {uid: query.filter_by(interlocutor_uid = uid).order_by(model.time) for uid in uids}

        return queries

    def dataline_messages(self):
        """按设备会话读取数据线消息；旧版数据库无此表时返回空。"""
        model = self._models["nt_msg"]["dataline_msg_table"]
        engine = self._engines.get("nt_msg")
        if not engine or not inspect(engine).has_table(model.__tablename__):
            return {}

        query = self.session.query(model)
        partitions = self.session.query(
            model.UNK_10, model.interlocutor_uid
        ).distinct().all()
        queries = {}
        for sort_no, uid in partitions:
            key = uid or f'dataline-{sort_no}'
            if sort_no is not None:
                partition_query = query.filter_by(UNK_10=sort_no)
            else:
                partition_query = query.filter_by(interlocutor_uid=uid)
            queries[key] = partition_query.order_by(model.time)
        return queries

    def self_uid_mapping(self):
        """返回 uid 映射表的首项，即当前登录账号自身。

        nt_uid_mapping_table 的第一条（按主键 48901 升序）恒为本账号，
        据此可直接取到当前账号的 uid 与 qq 号，无需扫描消息反推。
        """
        model = self._models["nt_msg"]["nt_uid_mapping_table"]
        return self.session.query(model).order_by(model.id).first()

    def group_messages(self, filters):
        model = self._models["nt_msg"]["group_msg_table"]
        query = self.session.query(model)
        if not filters:
            filters = [row[0] for row in self.session.query(model.mixed_group_num).distinct().all()]
        queries = {num: query.filter_by(mixed_group_num = num).order_by(model.time) for num in filters}
        return queries

    def profile_info(self, uid):
        model = self._models["profile_info"]["profile_info_v6"]
        return self.session.query(model).filter_by(uid = uid).first()

    def group_info(self, group_num):
        model = self._models["group_info"]["group_list"]
        return self.session.query(model) \
            .filter_by(group_number = group_num) \
            .first()

from .models import *
