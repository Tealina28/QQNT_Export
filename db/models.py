from sqlalchemy import String, LargeBinary, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship, object_session

import element_pb2
from .man import DatabaseManager

__all__ = ["C2cMessage", "GroupMessage", "UidMapping", ]

profile_map = {}

Base = declarative_base()


class Message():
    id: Mapped[int] = mapped_column("40001", primary_key=True)
    random: Mapped[int] = mapped_column("40002")
    seq: Mapped[int] = mapped_column("40003")
    chat_type: Mapped[int] = mapped_column("40010")
    msg_type: Mapped[int] = mapped_column("40011")
    sub_msg_type: Mapped[int] = mapped_column("40012")
    sender_flag: Mapped[int] = mapped_column("40013")
    sender_uid: Mapped[str] = mapped_column("40020", String(24))  # Tencent internal UID
    UNK_08: Mapped[int] = mapped_column("40026")

    UNK_11: Mapped[int] = mapped_column("40040")
    status: Mapped[int] = mapped_column("40041")
    time: Mapped[int] = mapped_column("40050")  # time message sent
    UNK_14: Mapped[int] = mapped_column("40052")

    nickname: Mapped[str] = mapped_column("40093", Text)  # only self, otherwise basically empty
    message_body: Mapped[bytes] = mapped_column("40800", LargeBinary)  # protobuf
    UNK_18: Mapped[bytes] = mapped_column("40900",
                                          LargeBinary)  # When msg_type == 8, stores a cache of forwarded message.When 9, stores the quoted messages.
    UNK_19: Mapped[int] = mapped_column("40105")
    UNK_20: Mapped[int] = mapped_column("40005")
    timestamp_day: Mapped[int] = mapped_column("40058")  # Time at 00:00 the day
    UNK_22: Mapped[int] = mapped_column("40006")

    UNK_24: Mapped[bytes] = mapped_column("40600", LargeBinary)  # If the value is 14 00 (hex), is a quoted message

    quoted_seq: Mapped[int] = mapped_column("40850")  # seq of the message which this message quoted
    UNK_27: Mapped[int] = mapped_column("40851")
    UNK_28: Mapped[bytes] = mapped_column("40601", LargeBinary)  # always null
    UNK_29: Mapped[bytes] = mapped_column("40801", LargeBinary)  # protobuf
    # protobuf, insufficient resource, related with a file?
    UNK_30: Mapped[bytes] = mapped_column("40605", LargeBinary)
    sender_num: Mapped[int] = mapped_column("40033")  # qq num
    UNK_33: Mapped[int] = mapped_column("40062")
    UNK_34: Mapped[int] = mapped_column("40083")
    UNK_35: Mapped[int] = mapped_column("40084")

    @property
    def elements(self):
        elements = element_pb2.Elements()
        try:
            elements.ParseFromString(self.message_body)
            return elements
        except:
            return elements


@DatabaseManager.register_model("nt_msg")
class C2cMessage(Base, Message):
    """
    C2c Message Table
    nt_msg.db -> c2c_msg_table
    """
    __tablename__ = "c2c_msg_table"

    # https://github.com/QQBackup/qq-win-db-key/issues/52

    interlocutor_uid: Mapped[str] = mapped_column("40021", String(24),
                                                  ForeignKey("nt_uid_mapping_table.48902"))  # Tencent internal UID
    UNK_10: Mapped[int] = mapped_column("40027")  # group num
    UNK_15: Mapped[str] = mapped_column("40090", Text)  # group name card
    UNK_23: Mapped[int] = mapped_column("40100")  # @ status
    UNK_25: Mapped[int] = mapped_column("40060")
    interlocutor_num: Mapped[int] = mapped_column("40030")  # qq num

    @property
    def profile_info(self):
        if self.interlocutor_uid in profile_map:
            return profile_map[self.interlocutor_uid]
        query_result = (
            object_session(self)
            .query(ProfileInfo)
            .filter(ProfileInfo.uid == self.interlocutor_uid)
            .first()
        )
        profile_map[self.interlocutor_uid] = query_result
        return query_result

    mapping = relationship('UidMapping', back_populates='c2c_messages')


@DatabaseManager.register_model("nt_msg")
class GroupMessage(Base, Message):
    """
    Group Message Table
    nt_msg.db -> group_msg_table
    """
    __tablename__ = "group_msg_table"

    group_num: Mapped[str] = mapped_column("40021", String(24))
    group_num2: Mapped[int] = mapped_column("40027")
    group_name_card: Mapped[str] = mapped_column("40090", Text)  # group name card
    at_status: Mapped[int] = mapped_column("40100")  # @ status
    group_status: Mapped[int] = mapped_column("40060")
    group_num3: Mapped[int] = mapped_column("40030")

    @hybrid_property
    def mixed_group_num(self):
        return self.group_num or self.group_num2 or self.group_num3


@DatabaseManager.register_model("nt_msg")
class UidMapping(Base):
    """
    Uid Mapping Table
    nt_msg.db -> nt_uid_mapping_table
    """
    __tablename__ = "nt_uid_mapping_table"

    id: Mapped[int] = mapped_column("48901", primary_key=True)
    uid: Mapped[str] = mapped_column("48902", String(24), )
    UNK_02: Mapped[str] = mapped_column("48912", nullable=True)
    qq_num: Mapped[int] = mapped_column("1002")

    c2c_messages = relationship("C2cMessage", back_populates="mapping")


@DatabaseManager.register_model("profile_info")
class ProfileInfo(Base):
    """
    好友信息
    profile_info.db -> profile_info_v6
    """
    __tablename__ = "profile_info_v6"
    qid: Mapped[str] = mapped_column("1001")
    qq_num: Mapped[int] = mapped_column("1002")
    nickname: Mapped[str] = mapped_column("20002")
    UNK_4: Mapped[str] = mapped_column("24106")
    UNK_5: Mapped[str] = mapped_column("24107")
    UNK_6: Mapped[str] = mapped_column("24108")
    UNK_7: Mapped[str] = mapped_column("24109")
    remark: Mapped[str] = mapped_column("20009")
    signature: Mapped[str] = mapped_column("20011")
    uid: Mapped[str] = mapped_column("1000", primary_key=True)
    UNK_11: Mapped[int] = mapped_column("20001")
    UNK_12: Mapped[int] = mapped_column("20003")
    avatar_url: Mapped[str] = mapped_column("20004")
    UNK_14: Mapped[int] = mapped_column("20005")
    UNK_15: Mapped[int] = mapped_column("20006")
    UNK_16: Mapped[int] = mapped_column("20007")
    UNK_17: Mapped[int] = mapped_column("20008")
    UNK_18: Mapped[int] = mapped_column("20010")
    UNK_19: Mapped[int] = mapped_column("20012")
    UNK_20: Mapped[int] = mapped_column("20014")
    UNK_21: Mapped[bytes] = mapped_column("20017")
    UNK_22: Mapped[int] = mapped_column("20016")
    UNK_23: Mapped[int] = mapped_column("24103")
    UNK_24: Mapped[bytes] = mapped_column("20042")
    UNK_25: Mapped[bytes] = mapped_column("20059")
    UNK_26: Mapped[int] = mapped_column("20060")
    UNK_27: Mapped[int] = mapped_column("20061")
    UNK_28: Mapped[int] = mapped_column("20043")
    UNK_29: Mapped[int] = mapped_column("20048")
    UNK_30: Mapped[int] = mapped_column("20037")
    UNK_31: Mapped[int] = mapped_column("20056")
    UNK_32: Mapped[int] = mapped_column("20067")
    UNK_33: Mapped[bytes] = mapped_column("20057")
    UNK_34: Mapped[int] = mapped_column("20070")
    UNK_35: Mapped[int] = mapped_column("20071")
    UNK_36: Mapped[bytes] = mapped_column("21000")
    relation: Mapped[bytes] = mapped_column("20072")
    UNK_38: Mapped[int] = mapped_column("20075")
    UNK_39: Mapped[bytes] = mapped_column("20066")
    UNK_40: Mapped[int] = mapped_column("24104")
    UNK_41: Mapped[bytes] = mapped_column("24105")
    UNK_42: Mapped[int] = mapped_column("24110")
    UNK_43: Mapped[int] = mapped_column("24111")
