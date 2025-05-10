from collections import defaultdict

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm.query import Query

__all__ = ["DatabaseManager"]


class DatabaseManager:
    _models = defaultdict(defaultdict)
    _loaded = set()
    _sessions = {}

    @classmethod
    def register_model(cls, db_id: str) -> callable:
        def wrapper(model):
            cls._models[db_id][model.__tablename__] = model
            return model

        return wrapper

    def __new__(cls, db_path):
        # Check for existing files corresponding to registered models and add them to the `_load` set
        for db_filename in cls._models.keys():
            if (db_path / f"{db_filename}.db").exists():
                cls._loaded.add(db_filename)
        for db_filename in cls._loaded:
            cls._sessions[db_filename] = Session(create_engine(f"sqlite:///{db_path / f'{db_filename}.db'}"))
        return super(DatabaseManager, cls).__new__(cls)

    def __init__(self, db_path):
        pass

    def num_to_uid(self, num: int) -> str:
        model = self._models["nt_msg"]["nt_uid_mapping_table"]
        return self._sessions["nt_msg"].query(model).filter(model.qq_num == num).first().uid

    def c2c_messages(self,filters) -> Query:
        model = self._models["nt_msg"]["c2c_msg_table"]
        query = self._sessions["nt_msg"].query(model)
        if filters:
            uids = [self.num_to_uid(num) for num in filters]
            return query.filter(model.interlocutor_uid.in_(uids)).order_by(model.time)
        else:
            return query.order_by(model.time)


    def group_messages(self,filters) -> Query:
        model = self._models["nt_msg"]["group_msg_table"]
        query = self._sessions["nt_msg"].query(model)
        return (query.filter(model.mixed_group_num.in_(filters)) if filters else query).order_by(model.time)

from .models import *