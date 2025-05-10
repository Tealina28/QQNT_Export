from datetime import datetime

from sqlalchemy import String, LargeBinary, Text, ForeignKey
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .man import DatabaseManager

import element_pb2
import elements

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

    elements_classes = {
        1: elements.Text,
        2: elements.Image,
        3: elements.File,
        6: elements.Emoji,
        8: elements.Notice,
        10: elements.Application,
        21: elements.Call,
        22: elements.Feed
    }

    @property
    def readable_time(self):
        return datetime.fromtimestamp(self.time).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def elements(self):
        elements = element_pb2.Elements()
        try:
            elements.ParseFromString(self.message_body)
            return elements
        except:
            return elements

    def parse(self):
        self.contents = []
        for element in self.elements.elements:
            self.contents.append(self._parse_single(element))

    def _parse_single(self, element):
        if element.type in self.elements_classes:
            return self.elements_classes[element.type](element).content
        elif element.type == 7:
            result = self._parse_single(element.quotedElement)
            if result[0]:
                result = ("[被引用的消息]" + result[0], result[1])
            else:
                result = ("[被引用的消息]", result[1])
            return result

        return None, None


@DatabaseManager.register_model("nt_msg")
class C2cMessage(Base,Message):
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
    interlocutor_num: Mapped[int] = mapped_column("40030") # qq num

    mapping = relationship('UidMapping', back_populates='c2c_messages')

    @property
    def direction(self):
        if self.sender_flag == 0:
            return "收"
        elif self.sender_flag == 1 or 2:
            return "发"
        elif self.sender_flag == 5:
            return "转发"

        return "未知"

    def write(self, output_path):
        txt_path = output_path / f"{self.mapping.qq_num if self.mapping else self.interlocutor_num}.txt"
        with txt_path.open(mode='a', encoding='utf-8') as f:
            f.write(f"{self.readable_time} {self.direction}\n")

            for content in self.contents:
                f.write(f"{content[0]}\n{content[1]}\n")

            f.write("\n")


@DatabaseManager.register_model("nt_msg")
class GroupMessage(Base,Message):
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
        return self.group_num or  self.group_num2 or  self.group_num3

    def write(self, output_path):
        txt_path = output_path / f"{self.mixed_group_num}.txt"
        with txt_path.open(mode='a', encoding='utf-8') as f:
            f.write(f"{self.readable_time} {self.group_name_card or self.nickname or self.sender_num}\n")

            for content in self.contents:
                f.write(f"{content[0]}\n{content[1]}\n")

            f.write("\n")

@DatabaseManager.register_model("nt_msg")
class UidMapping(Base):
    """
    Uid Mapping Table
    nt_msg.db -> nt_uid_mapping_table
    """
    __tablename__ = "nt_uid_mapping_table"

    id: Mapped[int] = mapped_column("48901", primary_key=True)
    uid: Mapped[str] = mapped_column("48902", String(24), )
    UNK_02: Mapped[str] = mapped_column("48912",nullable=True)
    qq_num: Mapped[int] = mapped_column("1002")

    c2c_messages = relationship("C2cMessage", back_populates="mapping")
