from models import *


def read_messages(session):
    return session.query(GroupMessage).order_by(GroupMessage.time).all()
