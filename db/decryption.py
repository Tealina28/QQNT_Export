"""Android QQNT database directory decryption.

The public entry point in this module deliberately has no dependency on
SQLAlchemy or the rest of the export pipeline.  SQLCipher is imported only
when at least one encrypted database needs to be processed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


SQLITE_HEADER = b"SQLite format 3\x00"
QQNT_HEADER_SIZE = 1024
QQNT_HEADER_MAGIC = b"QQ_NT DB"
QQNT_TOKEN_OFFSET = 46
QQNT_TOKEN_SIZE = 8
SQLCIPHER_PAGE_SIZE = 4096
MANIFEST_NAME = ".qqnt-export-decryption.json"
MANIFEST_FORMAT = "QQNT_Export Android QQNT plaintext databases"
MANIFEST_VERSION = 1
GPRO_DATABASE_PREFIXES = ("gpro_v1-6_u_", "en_gpro_v1-6_u_")

_TOKEN_PATTERN = re.compile(rb"[A-Za-z0-9]{8}\Z")
logger = logging.getLogger(__name__)


class DecryptionError(RuntimeError):
    """Base class for directory decryption failures."""


class ValidationError(DecryptionError):
    """The source, destination, UID, or a QQNT wrapper is invalid."""


class DependencyError(DecryptionError):
    """The optional SQLCipher dependency is unavailable."""


class DatabaseDecryptionError(DecryptionError):
    """A database could not be decrypted or validated."""


class PublishError(DecryptionError):
    """A complete staged result could not be published safely."""


@dataclass(frozen=True)
class _SourceDatabase:
    path: Path
    kind: Literal["plaintext", "encrypted"]
    snapshot: tuple[int, int, int, int]
    token: str | None = None


@dataclass(frozen=True)
class _DestinationState:
    directory_snapshot: tuple[int, int, int, int] | None
    entries: tuple[tuple[str, tuple[int, int, int, int]], ...] = ()
    database_names: tuple[str, ...] = ()


def decrypt_database_directory(
    source_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    uid: str,
    overwrite: bool = False,
) -> Path:
    """Decrypt supported top-level ``*.db`` files as one atomic batch.

    Plain SQLite databases are copied unchanged.  Android QQNT wrapped
    SQLCipher databases are unwrapped and exported as ordinary SQLite files.
    Known unsupported ``gpro_v1-6_u_*.db`` files are skipped explicitly.
    The destination directory is published only after every database has
    succeeded and passed a lightweight readability check.

    Args:
        source_path: Directory copied from Android QQNT's ``nt_db`` storage.
        output_path: New directory that will contain all plaintext databases.
        uid: The account QUID (normally beginning with ``u_``).
        overwrite: Replace an existing destination directory after staging a
            complete new result.  Only a clean destination previously created
            by this module can be replaced; existing files are never merged.

    Returns:
        The absolute path of the published plaintext database directory.

    Raises:
        ValidationError: If the inputs, wrapper header, token, or journal state
            are unsafe or unsupported.
        DependencyError: If encrypted input is present but SQLCipher is not
            installed.
        DatabaseDecryptionError: If any database fails to decrypt or validate.
        PublishError: If the staged directory cannot be published safely.
    """

    source = _resolve_source_directory(source_path)
    destination = _resolve_destination(output_path)
    _validate_path_relationship(source, destination)
    normalized_uid = _validate_uid(uid)
    if not isinstance(overwrite, bool):
        raise ValidationError("overwrite 必须是布尔值")

    databases = _inspect_source_databases(source)
    destination_state = _prepare_destination_parent(destination, overwrite)

    sqlcipher = None
    if any(database.kind == "encrypted" for database in databases):
        sqlcipher = _load_sqlcipher()

    try:
        stage = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.partial-",
                dir=destination.parent,
            )
        )
    except OSError as exc:
        raise PublishError(f"无法创建解密暂存目录：{destination.parent}") from exc

    try:
        try:
            os.chmod(stage, 0o700)
            work = stage / ".work"
            work.mkdir(mode=0o700)
        except OSError as setup_exc:
            raise PublishError(f"无法初始化解密暂存目录：{stage}") from setup_exc
        for database in databases:
            output_partial = stage / f".{database.path.name}.partial"
            output_final = stage / database.path.name
            try:
                if database.kind == "plaintext":
                    _copy_plaintext_database(database, output_partial)
                else:
                    assert sqlcipher is not None
                    _decrypt_wrapped_database(
                        database,
                        output_partial,
                        work,
                        normalized_uid,
                        sqlcipher,
                    )
                os.chmod(output_partial, 0o600)
                _validate_plaintext_database(output_partial)
                os.replace(output_partial, output_final)
            except DecryptionError:
                raise
            except Exception as exc:
                raise DatabaseDecryptionError(
                    f"处理数据库 {database.path.name} 失败：{exc}"
                ) from exc

        _assert_batch_unchanged(databases)
        try:
            shutil.rmtree(work)
        except OSError as cleanup_exc:
            raise PublishError(f"无法清理解密过程文件：{work}") from cleanup_exc
        _write_manifest(stage, databases)
        _assert_batch_unchanged(databases)
        _publish_directory(
            stage,
            destination,
            overwrite,
            destination_state,
        )
    except BaseException as exc:
        cleanup_error = _remove_stage_directory(stage)
        if cleanup_error is not None:
            message = (
                f"处理失败，且暂存目录清理失败；敏感明文可能保留在 "
                f"{stage}：{cleanup_error}"
            )
            if isinstance(exc, Exception):
                raise PublishError(message) from exc
            exc.add_note(message)
        raise

    return destination


def _resolve_source_directory(path: str | os.PathLike[str]) -> Path:
    try:
        source = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValidationError(f"加密数据库目录无效：{path!s}") from exc
    if not source.is_dir():
        raise ValidationError(f"加密数据库路径不是目录：{source}")
    return source


def _resolve_destination(path: str | os.PathLike[str]) -> Path:
    try:
        return Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValidationError(f"解密输出目录无效：{path!s}") from exc


def _validate_path_relationship(source: Path, destination: Path) -> None:
    if source == destination:
        raise ValidationError("解密输出目录不能与加密数据库目录相同")
    if source in destination.parents or destination in source.parents:
        raise ValidationError("加密数据库目录与解密输出目录不能互相包含")


def _validate_uid(uid: str) -> str:
    if not isinstance(uid, str):
        raise ValidationError("QUID 必须是字符串")
    normalized = uid.strip()
    if not normalized:
        raise ValidationError("QUID 不能为空")
    if normalized != uid or any(character.isspace() for character in uid):
        raise ValidationError("QUID 不能包含首尾空白或空白字符")
    return normalized


def _inspect_source_databases(source: Path) -> list[_SourceDatabase]:
    try:
        entries = list(source.iterdir())
        candidates = sorted(
            (
                entry
                for entry in entries
                if _is_supported_database_name(entry.name)
            ),
            key=lambda entry: entry.name,
        )
    except OSError as exc:
        raise ValidationError(f"无法列出数据库目录：{source}") from exc
    _reject_directory_active_journals(source, entries)
    skipped_gpro_count = sum(
        _is_gpro_database_name(entry.name) for entry in entries
    )
    if skipped_gpro_count:
        logger.warning(
            "跳过已知不兼容的 gpro_v1-6_u_*.db / "
            "en_gpro_v1-6_u_*.db（共 %s 个）",
            skipped_gpro_count,
        )
    if not candidates:
        raise ValidationError(f"目录中没有可处理的顶层 .db 文件：{source}")

    databases: list[_SourceDatabase] = []
    for path in candidates:
        try:
            file_stat = path.lstat()
        except OSError as exc:
            raise ValidationError(f"无法读取数据库文件信息：{path}") from exc
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValidationError(f"顶层 .db 项不是普通文件：{path}")

        try:
            with path.open("rb") as source_file:
                header = source_file.read(QQNT_HEADER_SIZE)
        except OSError as exc:
            raise ValidationError(f"无法读取数据库文件：{path}") from exc

        snapshot = _stat_snapshot(file_stat)
        if header.startswith(SQLITE_HEADER):
            databases.append(_SourceDatabase(path, "plaintext", snapshot))
            continue

        token = _parse_qqnt_header(path, header, file_stat.st_size)
        databases.append(_SourceDatabase(path, "encrypted", snapshot, token))

    return databases


def _parse_qqnt_header(path: Path, header: bytes, file_size: int) -> str:
    if len(header) != QQNT_HEADER_SIZE:
        raise ValidationError(
            f"{path.name} 既不是明文 SQLite，也没有完整的 1024 字节 QQNT 头"
        )
    if QQNT_HEADER_MAGIC not in header:
        raise ValidationError(f"{path.name} 的 1024 字节头缺少 QQNT 标识")

    token_bytes = header[
        QQNT_TOKEN_OFFSET : QQNT_TOKEN_OFFSET + QQNT_TOKEN_SIZE
    ]
    if _TOKEN_PATTERN.fullmatch(token_bytes) is None:
        raise ValidationError(f"{path.name} 的 QQNT 8 字节密钥 token 无效")

    encrypted_size = file_size - QQNT_HEADER_SIZE
    if encrypted_size < SQLCIPHER_PAGE_SIZE:
        raise ValidationError(f"{path.name} 的加密数据库正文过短")
    if encrypted_size % SQLCIPHER_PAGE_SIZE != 0:
        raise ValidationError(
            f"{path.name} 去除 QQNT 头后的大小不是 {SQLCIPHER_PAGE_SIZE} 的整数倍"
        )
    return token_bytes.decode("ascii")


def _prepare_destination_parent(
    destination: Path,
    overwrite: bool,
) -> _DestinationState:
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise ValidationError(f"无法创建解密输出目录的父目录：{destination.parent}") from exc

    try:
        destination_stat = destination.lstat()
    except FileNotFoundError:
        return _DestinationState(None)
    except OSError as exc:
        raise ValidationError(f"无法检查解密输出路径：{destination}") from exc

    if not stat.S_ISDIR(destination_stat.st_mode):
        raise ValidationError(f"解密输出路径已存在且不是目录：{destination}")
    if not overwrite:
        raise ValidationError(f"解密输出目录已存在：{destination}")
    return _read_managed_destination(destination, destination_stat)


def _load_sqlcipher() -> Any:
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher
    except (ImportError, OSError) as exc:
        raise DependencyError(
            "解密加密数据库需要可选依赖 rotki-pysqlcipher3；"
            "请安装 requirements-decrypt.txt"
        ) from exc
    return sqlcipher


def _copy_plaintext_database(
    database: _SourceDatabase,
    destination: Path,
) -> None:
    try:
        with database.path.open("rb") as source_file, destination.open("xb") as output:
            shutil.copyfileobj(source_file, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise DatabaseDecryptionError(
            f"复制明文数据库 {database.path.name} 失败"
        ) from exc
    _assert_source_unchanged(database)


def _decrypt_wrapped_database(
    database: _SourceDatabase,
    destination: Path,
    work_directory: Path,
    uid: str,
    sqlcipher: Any,
) -> None:
    assert database.token is not None
    encrypted_body = work_directory / database.path.name
    _copy_encrypted_body(database, encrypted_body)
    key = _derive_key(uid, database.token)

    connection = None
    attached = False
    try:
        connection = sqlcipher.connect(str(encrypted_body))
        cursor = connection.cursor()
        cursor.execute(f"PRAGMA key = '{key}'")
        cursor.execute(f"PRAGMA cipher_page_size = {SQLCIPHER_PAGE_SIZE}")
        cursor.execute("PRAGMA kdf_iter = 4000")
        cursor.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1")
        cursor.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
        cursor.execute("PRAGMA cipher_default_kdf_algorithm = PBKDF2_HMAC_SHA512")
        cursor.execute("PRAGMA cipher = 'aes-256-cbc'")

        # Force key/header validation before creating the plaintext database.
        cursor.execute("SELECT count(*) FROM sqlite_master").fetchone()
        user_version = int(cursor.execute("PRAGMA user_version").fetchone()[0])
        application_id = int(cursor.execute("PRAGMA application_id").fetchone()[0])

        cursor.execute(
            "ATTACH DATABASE ? AS plaintext KEY ''",
            (str(destination),),
        )
        attached = True
        cursor.execute("SELECT sqlcipher_export('plaintext')").fetchone()
        cursor.execute(f"PRAGMA plaintext.user_version = {user_version}")
        cursor.execute(f"PRAGMA plaintext.application_id = {application_id}")
        cursor.execute("DETACH DATABASE plaintext")
        attached = False
        connection.commit()
        cursor.close()
    except Exception as exc:
        raise DatabaseDecryptionError(
            f"解密数据库 {database.path.name} 失败，请检查 QUID、数据库头和版本"
        ) from exc
    finally:
        if connection is not None:
            if attached:
                try:
                    connection.execute("DETACH DATABASE plaintext")
                except Exception:
                    pass
            connection.close()
        try:
            encrypted_body.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        with destination.open("rb+") as output:
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise DatabaseDecryptionError(
            f"无法同步解密数据库 {database.path.name}"
        ) from exc


def _copy_encrypted_body(database: _SourceDatabase, destination: Path) -> None:
    try:
        with database.path.open("rb") as source_file, destination.open("xb") as output:
            source_file.seek(QQNT_HEADER_SIZE)
            shutil.copyfileobj(source_file, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(destination, 0o600)
    except OSError as exc:
        raise DatabaseDecryptionError(
            f"读取加密数据库 {database.path.name} 失败"
        ) from exc
    _assert_source_unchanged(database)


def _derive_key(uid: str, token: str) -> str:
    uid_hash = hashlib.md5(uid.encode("utf-8")).hexdigest()
    return hashlib.md5(f"{uid_hash}{token}".encode("ascii")).hexdigest()


def _validate_plaintext_database(path: Path) -> None:
    try:
        with path.open("rb") as database_file:
            if database_file.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                raise DatabaseDecryptionError(
                    f"输出数据库 {path.name} 没有 SQLite 文件头"
                )

        uri = f"{path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except DatabaseDecryptionError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseDecryptionError(
            f"输出数据库 {path.name} 无法作为明文 SQLite 读取"
        ) from exc


def _assert_batch_unchanged(databases: list[_SourceDatabase]) -> None:
    _reject_directory_active_journals(databases[0].path.parent)
    _assert_database_set_unchanged(databases)
    for database in databases:
        _assert_source_unchanged(database)
    _assert_database_set_unchanged(databases)
    _reject_directory_active_journals(databases[0].path.parent)


def _assert_database_set_unchanged(databases: list[_SourceDatabase]) -> None:
    source = databases[0].path.parent
    expected = {database.path.name for database in databases}
    try:
        current = {
            entry.name
            for entry in source.iterdir()
            if _is_supported_database_name(entry.name)
        }
    except OSError as exc:
        raise ValidationError(f"无法重新检查数据库目录：{source}") from exc
    if current != expected:
        added = sorted(current - expected)
        removed = sorted(expected - current)
        changes = []
        if added:
            changes.append(f"新增 {', '.join(added)}")
        if removed:
            changes.append(f"移除 {', '.join(removed)}")
        raise ValidationError(
            f"处理期间顶层 .db 文件集合发生变化：{'; '.join(changes)}"
        )


def _is_supported_database_name(name: str) -> bool:
    if not name.endswith(".db"):
        return False
    return not _is_gpro_database_name(name)


def _is_gpro_database_name(name: str) -> bool:
    return name.endswith(".db") and name.startswith(GPRO_DATABASE_PREFIXES)


def _assert_source_unchanged(database: _SourceDatabase) -> None:
    try:
        current = database.path.lstat()
    except OSError as exc:
        raise ValidationError(f"处理期间源数据库消失：{database.path}") from exc
    if not stat.S_ISREG(current.st_mode):
        raise ValidationError(f"处理期间源数据库类型发生变化：{database.path}")
    if _stat_snapshot(current) != database.snapshot:
        raise ValidationError(f"处理期间源数据库发生变化：{database.path}")


def _reject_active_journals(database_path: Path) -> None:
    is_gpro = _is_gpro_database_name(database_path.name)
    for suffix, label in (("-wal", "WAL"), ("-journal", "回滚日志")):
        journal_path = database_path.with_name(f"{database_path.name}{suffix}")
        try:
            if journal_path.exists() and journal_path.stat().st_size > 0:
                if is_gpro:
                    raise ValidationError(
                        f"检测到跳过的 gpro 数据库存在非空{label}；"
                        "请关闭 QQ 后重新复制数据库目录"
                    )
                raise ValidationError(
                    f"检测到非空{label}文件 {journal_path.name}；"
                    "请关闭 QQ 后重新复制数据库目录"
                )
        except OSError as exc:
            if is_gpro:
                raise ValidationError(
                    f"无法检查跳过的 gpro 数据库{label}"
                ) from exc
            raise ValidationError(f"无法检查日志文件：{journal_path}") from exc


def _reject_directory_active_journals(
    source: Path,
    entries: list[Path] | None = None,
) -> None:
    if entries is None:
        try:
            entries = list(source.iterdir())
        except OSError as exc:
            raise ValidationError(f"无法检查数据库目录日志文件：{source}") from exc
    for entry in entries:
        if entry.name.endswith(".db"):
            _reject_active_journals(entry)


def _stat_snapshot(file_stat: os.stat_result) -> tuple[int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


def _write_manifest(
    stage: Path,
    databases: list[_SourceDatabase],
) -> None:
    database_names = sorted(database.path.name for database in databases)
    manifest = {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "databases": database_names,
    }
    serialized = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    partial = stage / f".{MANIFEST_NAME}.partial"
    final = stage / MANIFEST_NAME
    try:
        with partial.open("xb") as manifest_file:
            manifest_file.write(serialized)
            manifest_file.flush()
            os.fsync(manifest_file.fileno())
        os.chmod(partial, 0o600)
        os.replace(partial, final)
    except OSError as exc:
        raise PublishError(f"无法写入解密目录清单：{final}") from exc


def _read_managed_destination(
    destination: Path,
    directory_stat: os.stat_result,
) -> _DestinationState:
    manifest_path = destination / MANIFEST_NAME
    try:
        manifest_before = manifest_path.lstat()
        if not stat.S_ISREG(manifest_before.st_mode):
            raise ValidationError(f"解密输出目录清单不是普通文件：{manifest_path}")
        with manifest_path.open("rb") as manifest_file:
            serialized = manifest_file.read(4 * 1024 * 1024 + 1)
        if len(serialized) > 4 * 1024 * 1024:
            raise ValidationError(f"解密输出目录清单过大：{manifest_path}")
        manifest_after = manifest_path.lstat()
        if _stat_snapshot(manifest_before) != _stat_snapshot(manifest_after):
            raise ValidationError(f"读取期间解密输出目录清单发生变化：{manifest_path}")
        manifest = json.loads(serialized.decode("utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(
            f"拒绝覆盖未受管理的目录（缺少 {MANIFEST_NAME}）；"
            f"请改用新的解密输出路径：{destination}"
        ) from exc
    except ValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"无法读取有效的解密输出目录清单：{manifest_path}") from exc

    if not isinstance(manifest, dict) or set(manifest) != {
        "format",
        "version",
        "databases",
    }:
        raise ValidationError(f"解密输出目录清单结构无效：{manifest_path}")
    if manifest["format"] != MANIFEST_FORMAT or not (
        isinstance(manifest["version"], int)
        and not isinstance(manifest["version"], bool)
        and manifest["version"] == MANIFEST_VERSION
    ):
        raise ValidationError(f"解密输出目录清单版本不受支持：{manifest_path}")

    raw_names = manifest["databases"]
    if not isinstance(raw_names, list) or not raw_names:
        raise ValidationError(f"解密输出目录清单没有数据库：{manifest_path}")
    if any(
        not isinstance(name, str)
        or not name.endswith(".db")
        or Path(name).name != name
        for name in raw_names
    ):
        raise ValidationError(f"解密输出目录清单包含无效文件名：{manifest_path}")
    database_names = tuple(sorted(raw_names))
    if len(database_names) != len(set(database_names)):
        raise ValidationError(f"解密输出目录清单包含重复文件名：{manifest_path}")

    try:
        entries_by_name = {entry.name: entry for entry in destination.iterdir()}
    except OSError as exc:
        raise ValidationError(f"无法检查已有解密输出目录：{destination}") from exc
    expected_names = {*database_names, MANIFEST_NAME}
    if set(entries_by_name) != expected_names:
        raise ValidationError(
            f"已有解密输出目录包含清单之外的内容或缺少数据库：{destination}"
        )

    entry_snapshots = []
    for name in sorted(expected_names):
        entry = entries_by_name[name]
        try:
            entry_stat = entry.lstat()
        except OSError as exc:
            raise ValidationError(f"无法检查已有解密输出文件：{entry}") from exc
        if not stat.S_ISREG(entry_stat.st_mode):
            raise ValidationError(f"已有解密输出文件不是普通文件：{entry}")
        entry_snapshots.append((name, _stat_snapshot(entry_stat)))

    try:
        directory_after = destination.lstat()
    except OSError as exc:
        raise ValidationError(f"无法复核已有解密输出目录：{destination}") from exc
    if _stat_snapshot(directory_stat) != _stat_snapshot(directory_after):
        raise ValidationError(f"检查期间已有解密输出目录发生变化：{destination}")

    return _DestinationState(
        directory_snapshot=_stat_snapshot(directory_after),
        entries=tuple(entry_snapshots),
        database_names=database_names,
    )


def _remove_stage_directory(stage: Path) -> OSError | None:
    if not stage.exists():
        return None
    try:
        shutil.rmtree(stage)
    except OSError as exc:
        return exc
    if stage.exists():
        return OSError("目录在清理后仍然存在")
    return None


def _publish_directory(
    stage: Path,
    destination: Path,
    overwrite: bool,
    initial_state: _DestinationState,
) -> None:
    _assert_destination_unchanged(destination, initial_state)

    if initial_state.directory_snapshot is None:
        try:
            os.replace(stage, destination)
            return
        except BaseException as publish_exc:
            rollback_error = _rollback_new_directory(stage, destination)
            if rollback_error is not None:
                message = (
                    f"发布解密输出失败，且无法撤回目标 {destination}："
                    f"{rollback_error}"
                )
                if isinstance(publish_exc, Exception):
                    raise PublishError(message) from publish_exc
                publish_exc.add_note(message)
                raise
            if isinstance(publish_exc, Exception):
                raise PublishError(f"无法发布解密输出目录：{destination}") from publish_exc
            raise

    if not overwrite:
        raise PublishError(f"解密输出目录不允许覆盖：{destination}")

    backup = destination.with_name(
        f".{destination.name}.backup-{uuid.uuid4().hex}"
    )
    try:
        os.replace(destination, backup)
        backup_stat = backup.lstat()
        backup_state = _read_managed_destination(backup, backup_stat)
        if backup_state != initial_state:
            raise PublishError(f"解密输出目录在发布时发生变化：{destination}")
        os.replace(stage, destination)
    except BaseException as publish_exc:
        rollback_error = _rollback_published_directory(
            stage,
            destination,
            backup,
        )
        if rollback_error is not None:
            message = (
                "发布解密输出失败，且旧目录回滚失败；"
                f"请检查目标 {destination}、暂存目录 {stage} 和旧目录 {backup}："
                f"{rollback_error}"
            )
            if isinstance(publish_exc, Exception):
                raise PublishError(message) from publish_exc
            publish_exc.add_note(message)
            raise
        if isinstance(publish_exc, PublishError):
            raise
        if isinstance(publish_exc, Exception):
            raise PublishError(f"无法替换解密输出目录：{destination}") from publish_exc
        raise

    try:
        shutil.rmtree(backup)
    except BaseException as cleanup_exc:
        # The new batch is already complete and published.  Keep the backup
        # rather than risking loss of either complete directory.
        message = f"新解密目录已完整发布，但旧目录无法删除：{backup}"
        if isinstance(cleanup_exc, Exception):
            raise PublishError(message) from cleanup_exc
        cleanup_exc.add_note(message)
        raise


def _rollback_new_directory(stage: Path, destination: Path) -> OSError | None:
    if stage.exists() or not destination.exists():
        return None
    try:
        os.replace(destination, stage)
    except OSError as exc:
        return exc
    return None


def _assert_destination_unchanged(
    destination: Path,
    initial_state: _DestinationState,
) -> None:
    try:
        current = destination.lstat()
    except FileNotFoundError:
        if initial_state.directory_snapshot is None:
            return
        raise PublishError(f"已有解密输出目录在处理期间消失：{destination}")
    except OSError as exc:
        raise PublishError(f"无法重新检查解密输出目录：{destination}") from exc

    if initial_state.directory_snapshot is None:
        raise PublishError(f"解密输出路径在处理期间出现：{destination}")
    if not stat.S_ISDIR(current.st_mode):
        raise PublishError(f"解密输出路径在处理期间变为非目录：{destination}")
    try:
        current_state = _read_managed_destination(destination, current)
    except ValidationError as exc:
        raise PublishError(f"已有解密输出目录在处理期间失效：{destination}") from exc
    if current_state != initial_state:
        raise PublishError(f"解密输出目录在处理期间发生变化：{destination}")


def _rollback_published_directory(
    stage: Path,
    destination: Path,
    backup: Path,
) -> OSError | None:
    if not backup.exists():
        return None
    try:
        if destination.exists():
            if stage.exists():
                return OSError("目标目录与暂存目录同时存在，无法判定发布状态")
            os.replace(destination, stage)
        os.replace(backup, destination)
    except OSError as exc:
        return exc
    return None
