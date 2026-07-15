from collections import defaultdict
import logging

from sqlalchemy import create_engine, inspect, literal, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.query import Query

__all__ = ["DatabaseManager"]


logger = logging.getLogger(__name__)


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

    def _message_query(self, model):
        """返回可导出的消息查询，过滤 QQNT 的空占位行。

        msg_type=1 也可能带有有效的 40800，因此只排除 type 1 且
        40800/40900/40801/表情反应均为 NULL 的记录。其他未知类型保留。
        """
        return self.session.query(model).filter(or_(
            model.msg_type != 1,
            model.message_body.is_not(None),
            model.UNK_18.is_not(None),
            model.UNK_29.is_not(None),
            model.reactions_body.is_not(None),
        ))

    def c2c_messages(self, filters):
        model = self._models["nt_msg"]["c2c_msg_table"]
        query = self._message_query(model)
        if filters:
            uids = [self.num_to_uid(num) for num in filters]
        else:
            uids = [
                row[0] for row in query.with_entities(
                    model.interlocutor_uid
                ).distinct().all()
            ]

        queries = {uid: query.filter_by(interlocutor_uid = uid).order_by(model.time) for uid in uids}

        return queries

    def dataline_messages(self):
        """按设备会话读取数据线消息；旧版数据库无此表时返回空。"""
        model = self._models["nt_msg"]["dataline_msg_table"]
        engine = self._engines.get("nt_msg")
        if not engine or not inspect(engine).has_table(model.__tablename__):
            return {}

        query = self._message_query(model)
        partitions = query.with_entities(
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

    def system_emojis(self):
        """读取 QQ 系统表情的名称、类型和资源包信息。

        emoji.db 在旧版数据目录中可能不存在，因此将它视为可选数据库。
        """
        model = self._models["emoji"]["base_sys_emoji_table"]
        engine = self._engines.get("emoji")
        if not engine or not inspect(engine).has_table(model.__tablename__):
            return {}

        available_columns = {
            column['name']
            for column in inspect(engine).get_columns(model.__tablename__)
        }
        if not {'81211', '81212'} <= available_columns:
            return {}
        optional_columns = (
            ('81214', model.unicode_id),
            ('81226', model.emoji_type),
            ('81229', model.static_archive_url),
            ('81230', model.apng_archive_url),
        )
        try:
            rows = self.session.query(
                model.emoji_id,
                model.description,
                *(
                    column if name in available_columns else literal(None)
                    for name, column in optional_columns
                ),
            ).all()
        except SQLAlchemyError as exc:
            logger.warning('读取系统表情数据库失败，将使用内置映射: %s', exc)
            return {}

        return {
            emoji_id: {
                'description': description,
                'unicode_id': unicode_id,
                'emoji_type': emoji_type,
                'static_archive_url': static_archive_url,
                'apng_archive_url': apng_archive_url,
            }
            for (
                emoji_id,
                description,
                unicode_id,
                emoji_type,
                static_archive_url,
                apng_archive_url,
            ) in rows
            if emoji_id is not None and description
        }

    def system_emoji_names(self):
        """兼容只需要 ID 到外显文字的调用方。"""
        return {
            emoji_id: item['description']
            for emoji_id, item in self.system_emojis().items()
        }

    def group_messages(self, filters):
        model = self._models["nt_msg"]["group_msg_table"]
        query = self._message_query(model)
        if not filters:
            filters = [
                row[0] for row in query.with_entities(
                    model.mixed_group_num
                ).distinct().all()
            ]
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
