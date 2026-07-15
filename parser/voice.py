"""QQ NT PTT 缓存定位与 Tencent SILK 解码。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path


logger = logging.getLogger(__name__)
SILK_MAGIC = b'#!SILK_V3'
MAX_VOICE_BYTES = 100 * 1024 * 1024


def resolve_ptt_root(ptt_path: str | Path | None) -> Path | None:
    """接受 nt_qq、nt_data、Ptt 或其父目录，返回实际 Ptt 根目录。"""
    if not ptt_path:
        return None
    path = Path(ptt_path)
    candidates = (
        path / 'nt_data' / 'Ptt',
        path / 'Ptt',
        path,
    )
    return next((candidate for candidate in candidates if candidate.is_dir()), None)


def _relative_month(timestamp: int, delta: int) -> str:
    date = datetime.fromtimestamp(timestamp)
    month_index = date.year * 12 + date.month - 1 + delta
    year, month = divmod(month_index, 12)
    return f'{year:04d}-{month + 1:02d}'


def _safe_basename(filename: str | None) -> str:
    return str(filename or '').replace('\\', '/').rsplit('/', 1)[-1]


def _case_insensitive_file(directory: Path, filename: str) -> Path | None:
    direct = directory / filename
    if direct.is_file():
        return direct
    target = filename.casefold()
    try:
        return next(
            entry for entry in directory.iterdir()
            if entry.is_file() and entry.name.casefold() == target
        )
    except (OSError, StopIteration):
        return None


@lru_cache(maxsize=4096)
def find_ptt_file(
    ptt_path: str | Path | None,
    timestamp: int,
    filename: str | None,
    file_path: str | None = None,
) -> Path | None:
    """按显式路径或消息月份在 Ptt/<YYYY-MM>/Ori 中定位语音。"""
    if file_path:
        explicit = Path(file_path)
        if explicit.is_file():
            return explicit

    root = resolve_ptt_root(ptt_path)
    name = _safe_basename(filename)
    if not root or not name or not timestamp:
        return None

    try:
        months = tuple(_relative_month(int(timestamp), delta) for delta in (0, -1, 1))
    except (OSError, OverflowError, ValueError):
        return None
    for month in months:
        candidate = _case_insensitive_file(
            root / month / 'Ori',
            name,
        )
        if candidate:
            return candidate
    return None


def voice_resource_key(content: dict) -> str:
    """生成稳定且可安全用于文件名的语音资源键。"""
    md5 = str(content.get('md5') or '').lower()
    if len(md5) == 32 and all(char in '0123456789abcdef' for char in md5):
        return md5
    identity = '|'.join((
        str(content.get('filename') or ''),
        str(content.get('file_token') or ''),
        str(content.get('size') or ''),
    ))
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]


def normalize_tencent_silk(data: bytes) -> bytes | None:
    """把 QQ 的 0x02/0x03 + SILK 头统一成解码器接受的 0x02。"""
    index = data.find(SILK_MAGIC)
    if index < 0:
        return None
    return b'\x02' + data[index:]


def is_wav_file(path: Path) -> bool:
    try:
        with path.open('rb') as wav:
            header = wav.read(12)
    except OSError:
        return False
    return header.startswith(b'RIFF') and header[8:12] == b'WAVE'


def decode_silk_to_wav(source: Path, destination: Path) -> bool:
    """将 QQ SILK 文件解码为 24 kHz、单声道、16-bit WAV。"""
    if is_wav_file(destination):
        return True
    temporary = destination.with_suffix('.wav.tmp')
    try:
        if source.stat().st_size > MAX_VOICE_BYTES:
            raise ValueError('voice file is too large')
        silk = normalize_tencent_silk(source.read_bytes())
        if silk is None:
            raise ValueError('missing SILK_V3 header')

        import pysilk

        wav = pysilk.decode(silk, to_wav=True, sample_rate=24000)
        if not (
            isinstance(wav, bytes)
            and wav.startswith(b'RIFF')
            and wav[8:12] == b'WAVE'
        ):
            raise ValueError('decoder returned invalid WAV')

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(wav)
        temporary.replace(destination)
        return True
    except Exception as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        logger.warning('语音解码失败，将回退到文字: %s (%s)', source, exc)
        return False
