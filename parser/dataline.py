"""QQ 数据线（跨设备同步）会话的设备身份。"""

from collections.abc import Iterable


DATALINE_PHONE_UID = 'u_Wcc5rknRRqRO8y5gxMD6sA'
DATALINE_PC_UID = 'u_rK7NMsbv2ZjEGPdCuOiCfw'
DATALINE_PAD_UID = 'u_l7jpPIZxQo0mzJwoEt-SKw'

DATALINE_DEVICE_NAMES = {
    DATALINE_PHONE_UID: '我的手机',
    DATALINE_PC_UID: '我的电脑',
    DATALINE_PAD_UID: '我的平板',
}

DATALINE_DEVICE_UIDS = {
    'phone': DATALINE_PHONE_UID,
    'pc': DATALINE_PC_UID,
    'pad': DATALINE_PAD_UID,
}


def dataline_device_name(uid: str) -> str:
    """返回设备伪 UID 的显示名，未知 UID 原样返回。"""
    return DATALINE_DEVICE_NAMES.get(uid, uid)


def resolve_dataline_owner_id(value: str | None) -> str:
    """将 pc/phone/pad 设备名解析为数据线 ownerId。"""
    normalized = (value or 'pc').strip()
    if not normalized:
        normalized = 'pc'
    try:
        return DATALINE_DEVICE_UIDS[normalized.lower()]
    except KeyError as exc:
        raise ValueError(
            'dataline_owner 必须是 pc、phone 或 pad'
        ) from exc


def dataline_conversation_name(
    sender_uids: Iterable[str],
    owner_id: str = DATALINE_PC_UID,
    fallback_uid: str = '',
) -> str:
    """根据数据线消息发送者推断对端设备名称。"""
    peer_uids = {
        uid for uid in sender_uids
        if uid and uid != owner_id
    }
    if len(peer_uids) == 1:
        return dataline_device_name(next(iter(peer_uids)))
    if len(peer_uids) > 1:
        return '我的设备'
    return dataline_device_name(fallback_uid) if fallback_uid else '我的设备'
