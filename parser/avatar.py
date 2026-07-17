"""QQ 头像 URL 与本地缓存解析。"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def public_user_avatar_url(qq_num: int) -> str | None:
    if not qq_num:
        return None
    return f"https://q1.qlogo.cn/g?b=qq&nk={qq_num}&s=100"


def normalize_user_avatar_url(
    avatar_url: str | None,
    qq_num: int,
) -> str | None:
    """规范化 QQ 用户头像地址，地址缺失或无效时生成公共地址。"""
    fallback = public_user_avatar_url(qq_num)
    if not avatar_url:
        return fallback

    value = avatar_url.strip()
    if not value:
        return fallback
    try:
        parsed = urlsplit(value)
    except ValueError:
        return fallback

    hostname = (parsed.hostname or '').lower()
    is_qlogo = hostname == 'qlogo.cn' or hostname.endswith('.qlogo.cn')
    if not is_qlogo:
        return value
    if parsed.scheme not in ('', 'http', 'https'):
        return fallback

    query = parse_qsl(parsed.query, keep_blank_values=True)
    sizes = [item_value for key, item_value in query if key == 's']
    size = next((item_value for item_value in sizes if item_value), '100')
    query = [(key, item_value) for key, item_value in query if key != 's']
    query.append(('s', size))
    return urlunsplit((
        'https',
        parsed.netloc,
        parsed.path,
        urlencode(query),
        parsed.fragment,
    ))


def public_group_avatar_url(group_num: int | str) -> str | None:
    if not group_num:
        return None
    group = str(group_num)
    return f"https://p.qlogo.cn/gh/{group}/{group}/640/"


def avatar_hash_for_uid(uid: str) -> str:
    """QQ NT 本地头像缓存使用的三重 MD5。"""
    def md5(value: str) -> str:
        return hashlib.md5(value.encode('utf-8')).hexdigest()

    return md5(md5(md5(uid) + uid) + uid)


def find_local_avatar(
    avatar_path: str | Path | None,
    identity: str,
    scope: str = 'user',
) -> Path | None:
    if not avatar_path or not identity:
        return None
    root = Path(avatar_path)
    if root.name != 'avatar':
        root = root / 'avatar'
    image_hash = avatar_hash_for_uid(identity)
    bucket = image_hash[:2]
    for prefix in ('b_', 's_'):
        candidate = root / scope / bucket / f'{prefix}{image_hash}'
        if candidate.is_file():
            return candidate
    return None


def image_mime_type(path: Path) -> str:
    with path.open('rb') as image:
        header = image.read(16)
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if header.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'image/webp'
    return 'image/jpeg'


def image_data_url(path: Path) -> str:
    mime = image_mime_type(path)
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{encoded}'


def image_extension(path: Path) -> str:
    return {
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'image/jpeg': '.jpg',
    }[image_mime_type(path)]
