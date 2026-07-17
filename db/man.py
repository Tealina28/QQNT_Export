from collections import defaultdict
from dataclasses import dataclass
import logging

from sqlalchemy import and_, create_engine, inspect, literal, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.query import Query

__all__ = ["DatabaseManager", "GroupInfo"]


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroupInfo:
    """从群详情与群列表逐字段合并后的导出资料。"""

    group_number: int | str
    name: str | None = None
    remark: str | None = None
    owner_uid: str | None = None

    @property
    def display_name(self) -> str:
        return self.remark or self.name or str(self.group_number)


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
        """按索引列 40027 分区私聊，旧库空分区回退到 40021/40030。"""
        model = self._models["nt_msg"]["c2c_msg_table"]
        mapping_model = self._models["nt_msg"]["nt_uid_mapping_table"]
        query = self._message_query(model)

        if filters:
            mappings = (
                self.session.query(mapping_model)
                .filter(mapping_model.qq_num.in_(filters))
                .order_by(mapping_model.id)
                .all()
            )
            mapped_numbers = {
                str(mapping.qq_num)
                for mapping in mappings
            }
            for value in filters:
                if str(value) not in mapped_numbers:
                    # 保持既有的无效过滤值失败行为；前置校验属于 P2-4。
                    self.num_to_uid(value)
            requested_sort_nos = {mapping.id for mapping in mappings}
        else:
            mappings = []
            requested_sort_nos = None

        partition_query = (
            query.order_by(None)
            .filter(model.UNK_10.is_not(None))
        )
        if requested_sort_nos is not None:
            partition_query = partition_query.filter(
                model.UNK_10.in_(requested_sort_nos)
            )
        partition_rows = (
            partition_query
            .with_entities(
                model.UNK_10,
                model.interlocutor_uid,
                model.interlocutor_num,
            )
            .distinct()
            .all()
        )
        sort_nos = {row[0] for row in partition_rows}
        if not filters:
            mappings = (
                self.session.query(mapping_model)
                .filter(mapping_model.id.in_(sort_nos))
                .all()
            )
        mapping_by_sort_no = {
            mapping.id: mapping
            for mapping in mappings
        }

        candidates_by_sort_no = defaultdict(list)
        for sort_no, uid, qq_num in partition_rows:
            candidates_by_sort_no[sort_no].append(
                (uid, qq_num)
            )

        partition_conditions = defaultdict(list)
        identity_keys = defaultdict(set)
        number_keys = defaultdict(set)
        for sort_no in sorted(sort_nos):
            mapping = mapping_by_sort_no.get(sort_no)
            candidates = candidates_by_sort_no[sort_no]
            actual_uids = sorted({
                str(candidate[0])
                for candidate in candidates
                if candidate[0]
            })
            sort_keys = set()
            keys_by_number = defaultdict(set)
            for uid in actual_uids:
                key = uid
                sort_keys.add(key)
                identity_keys[uid].add(key)
                partition_conditions[key].append(and_(
                    model.UNK_10 == sort_no,
                    model.interlocutor_uid == uid,
                ))
                for candidate_uid, qq_num in candidates:
                    if str(candidate_uid or '') != uid or not qq_num:
                        continue
                    keys_by_number[str(qq_num)].add(key)
                    number_keys[str(qq_num)].add(key)

            for candidate_uid, qq_num in candidates:
                if candidate_uid:
                    continue
                matching_keys = (
                    keys_by_number.get(str(qq_num), set())
                    if qq_num else set()
                )
                mapping_key = (
                    (mapping.uid or mapping.UNK_02)
                    if mapping and (mapping.uid or mapping.UNK_02)
                    else None
                )
                if not actual_uids and mapping_key:
                    key = str(mapping_key)
                elif len(matching_keys) == 1:
                    key = next(iter(matching_keys))
                elif qq_num:
                    key = f'c2c-sort-{sort_no}-qq-{qq_num}'
                else:
                    missing_kind = 'null' if candidate_uid is None else 'empty'
                    key = f'c2c-sort-{sort_no}-{missing_kind}-uid'
                sort_keys.add(key)
                partition_conditions[key].append(and_(
                    model.UNK_10 == sort_no,
                    model.interlocutor_uid == candidate_uid,
                    model.interlocutor_num == qq_num,
                ))
                if qq_num:
                    number_keys[str(qq_num)].add(key)

            for identity in (
                mapping.uid if mapping else None,
                mapping.UNK_02 if mapping else None,
            ):
                if not identity:
                    continue
                identity = str(identity)
                if identity in sort_keys:
                    identity_keys[identity].add(identity)
                elif len(sort_keys) == 1:
                    identity_keys[identity].update(sort_keys)
            if mapping and mapping.qq_num:
                number_keys[str(mapping.qq_num)].update(sort_keys)

        fallback_rows = (
            query.order_by(None)
            .filter(model.UNK_10.is_(None))
            .with_entities(model.interlocutor_uid, model.interlocutor_num)
            .distinct()
            .all()
        )
        requested_numbers = {
            str(value) for value in filters
        } if filters else None
        selected_identities = set(identity_keys)
        if filters:
            selected_identities.update(
                str(identity)
                for mapping in mappings
                for identity in (mapping.uid, mapping.UNK_02)
                if identity
            )
        for uid, qq_num in fallback_rows:
            if (
                filters
                and str(qq_num) not in requested_numbers
                and str(uid) not in selected_identities
            ):
                continue
            if uid:
                matching_keys = identity_keys.get(str(uid), set())
            else:
                matching_keys = set()
            if not uid and qq_num:
                matching_keys = number_keys.get(str(qq_num), set())
            if len(matching_keys) == 1:
                key = next(iter(matching_keys))
            elif uid:
                key = str(uid)
            elif qq_num:
                key = f'c2c-qq-{qq_num}'
            else:
                key = self._c2c_fallback_key(uid)
            partition_conditions[key].append(and_(
                model.UNK_10.is_(None),
                model.interlocutor_uid == uid,
                model.interlocutor_num == qq_num,
            ))

        queries = {
            key: query.filter(or_(*conditions)).order_by(model.time)
            for key, conditions in partition_conditions.items()
        }
        return queries

    @staticmethod
    def _c2c_fallback_key(uid):
        if uid is None:
            return 'c2c-null-uid'
        if uid == '':
            return 'c2c-empty-uid'
        return uid

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
        """按群号索引 40027 分区，精确合并旧记录的空分区行。"""
        model = self._models["nt_msg"]["group_msg_table"]
        query = self._message_query(model)

        if filters:
            group_numbers = list(dict.fromkeys(
                self._normalize_group_number(value)
                for value in filters
            ))
        else:
            group_numbers = [
                self._normalize_group_number(row[0])
                for row in (
                    query.order_by(None)
                    .filter(model.group_num2.is_not(None))
                    .with_entities(model.group_num2)
                    .distinct()
                    .all()
                )
            ]
        indexed_group_numbers = set(group_numbers)

        fallback_conditions = defaultdict(list)
        fallback_rows = (
            query.order_by(None)
            .filter(model.group_num2.is_(None))
            .with_entities(model.group_num, model.group_num3)
            .distinct()
            .all()
        )
        for group_num, group_num3 in fallback_rows:
            if group_num not in (None, ''):
                key = self._normalize_group_number(group_num)
                condition = and_(
                    model.group_num2.is_(None),
                    model.group_num == group_num,
                )
            else:
                key = self._normalize_group_number(group_num3)
                condition = and_(
                    model.group_num2.is_(None),
                    model.group_num == group_num,
                    model.group_num3 == group_num3,
                )
            fallback_conditions[key].append(condition)
            if not filters and key not in group_numbers:
                group_numbers.append(key)

        queries = {}
        for group_num in group_numbers:
            conditions = []
            if filters or group_num in indexed_group_numbers:
                conditions.append(model.group_num2 == group_num)
            conditions.extend(fallback_conditions.get(group_num, []))
            queries[group_num] = (
                query.filter(or_(*conditions))
                .order_by(model.seq)
            )
        return queries

    @staticmethod
    def _normalize_group_number(value):
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return value
        return value

    def profile_info(self, uid):
        model = self._models["profile_info"]["profile_info_v6"]
        engine = self._engines.get("profile_info")
        if not engine:
            return None
        try:
            if not inspect(engine).has_table(model.__tablename__):
                return None
            return self.session.query(model).filter_by(uid=uid).first()
        except SQLAlchemyError:
            logger.warning(
                "读取用户资料数据库失败，使用消息字段降级"
            )
            return None

    @staticmethod
    def _nonempty_group_value(value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def _group_info_fields(self, engine, inspector, model, group_num, fields):
        """只投影表中实际存在的群资料列，兼容旧版残缺表结构。"""
        table_name = model.__tablename__
        try:
            if not inspector.has_table(table_name):
                return {}
            columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            if "60001" not in columns:
                return {}
            selected_fields = [
                field
                for field in fields
                if getattr(model, field).property.columns[0].name in columns
            ]
            if not selected_fields:
                return {}
            statement = (
                select(*(
                    getattr(model, field).label(field)
                    for field in selected_fields
                ))
                .where(model.group_number == group_num)
                .limit(1)
            )
            with engine.connect() as connection:
                row = connection.execute(statement).mappings().first()
        except SQLAlchemyError as exc:
            logger.warning(
                "读取群 %s 的 %s 资料失败，跳过该表: %s",
                group_num,
                table_name,
                exc,
            )
            return {}
        return dict(row) if row else {}

    def group_info(self, group_num) -> GroupInfo:
        """合并群详情与群列表；详情字段非空时优先。"""
        normalized_group_num = self._normalize_group_number(group_num)
        engine = self._engines.get("group_info")
        if not engine:
            return GroupInfo(group_number=normalized_group_num)

        try:
            inspector = inspect(engine)
        except SQLAlchemyError as exc:
            logger.warning(
                "检查群 %s 的资料库失败，使用群号降级: %s",
                normalized_group_num,
                exc,
            )
            return GroupInfo(group_number=normalized_group_num)

        detail_model = self._models["group_info"][
            "group_detail_info_ver1"
        ]
        list_model = self._models["group_info"]["group_list"]
        detail = self._group_info_fields(
            engine,
            inspector,
            detail_model,
            normalized_group_num,
            ("name", "remark", "owner_uid"),
        )
        group_list = self._group_info_fields(
            engine,
            inspector,
            list_model,
            normalized_group_num,
            ("name", "remark"),
        )

        def merged(field):
            detail_value = self._nonempty_group_value(detail.get(field))
            if detail_value is not None:
                return detail_value
            return self._nonempty_group_value(group_list.get(field))

        name = merged("name")
        remark = merged("remark")
        owner_uid = self._nonempty_group_value(detail.get("owner_uid"))
        return GroupInfo(
            group_number=normalized_group_num,
            name=str(name) if name is not None else None,
            remark=str(remark) if remark is not None else None,
            owner_uid=(
                str(owner_uid) if owner_uid is not None else None
            ),
        )

    def group_owner_uid(self, group_num) -> str | None:
        """兼容旧调用，群主 UID 与合并后的群资料保持一致。"""
        return self.group_info(group_num).owner_uid

from .models import *
