from models import *


def read_messages(session):
    return session.query(C2cMessage).order_by(C2cMessage.time).all()
