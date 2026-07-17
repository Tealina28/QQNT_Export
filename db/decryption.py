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
_UID_FRAGMENT_PATTERN = re.compile(r"u_[A-Za-z0-9_-]+")
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
class _SourceEntry:
    path: Path
    mode: int
    snapshot: tuple[int, int, int, int]


@dataclass(frozen=True)
class _SourceState:
    source: Path
    database_names: frozenset[str]
    entries: tuple[_SourceEntry, ...]


@dataclass(frozen=True)
class _DatabaseFailure:
    name: str
    stage: Literal["检查", "依赖", "复制", "解密", "验证", "暂存"]
    reason: Exception
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
    """Decrypt supported top-level ``*.db`` files with partial success.

    Plain SQLite databases are copied unchanged.  Android QQNT wrapped
    SQLCipher databases are unwrapped and exported as ordinary SQLite files.
    Known unsupported ``gpro_v1-6_u_*.db`` files are skipped explicitly.
    Per-database failures are logged and omitted; the destination is published
    when at least one database succeeds.  Directory journals, source snapshot,
    and destination publication safety remain batch-wide requirements.

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
        ValidationError: If a batch-wide input, journal, or source snapshot
            check is unsafe or invalid.
        DatabaseDecryptionError: If no database can be decrypted or validated.
        PublishError: If the staged directory cannot be published safely.
    """

    source = _resolve_source_directory(source_path)
    destination = _resolve_destination(output_path)
    _validate_path_relationship(source, destination)
    normalized_uid = _validate_uid(uid)
    if not isinstance(overwrite, bool):
        raise ValidationError("overwrite 必须是布尔值")

    source_state, databases, failures, skipped_count = (
        _inspect_source_databases(source)
    )
    for failure in failures:
        _log_database_failure(failure, normalized_uid)

    sqlcipher = None
    if any(database.kind == "encrypted" for database in databases):
        try:
            sqlcipher = _load_sqlcipher()
        except DependencyError as dependency_error:
            plaintext_databases = []
            for database in databases:
                if database.kind == "plaintext":
                    plaintext_databases.append(database)
                    continue
                failure = _DatabaseFailure(
                    database.path.name,
                    "依赖",
                    dependency_error,
                    database.token,
                )
                failures.append(failure)
                _log_database_failure(failure, normalized_uid)
            databases = plaintext_databases

    if not databases:
        _log_database_summary(0, len(failures), skipped_count)
        raise DatabaseDecryptionError(
            "没有数据库处理成功；未发布解密输出目录"
        )

    destination_state = _prepare_destination_parent(destination, overwrite)

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
        successful_databases: list[_SourceDatabase] = []
        for database in databases:
            output_partial = stage / f".{database.path.name}.partial"
            output_final = stage / database.path.name
            failure_stage: Literal[
                "复制", "解密", "验证", "暂存"
            ] = "复制" if database.kind == "plaintext" else "解密"
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
                failure_stage = "验证"
                os.chmod(output_partial, 0o600)
                _validate_plaintext_database(output_partial)
                failure_stage = "暂存"
                os.replace(output_partial, output_final)
                successful_databases.append(database)
            except Exception as exc:
                _remove_failed_database_artifacts(output_partial)
                failure = _DatabaseFailure(
                    database.path.name,
                    failure_stage,
                    exc,
                    database.token,
                )
                failures.append(failure)
                _log_database_failure(failure, normalized_uid)

        _assert_batch_unchanged(source_state)
        if not successful_databases:
            _log_database_summary(0, len(failures), skipped_count)
            raise DatabaseDecryptionError(
                "没有数据库处理成功；未发布解密输出目录"
            )
        try:
            shutil.rmtree(work)
        except OSError as cleanup_exc:
            raise PublishError(f"无法清理解密过程文件：{work}") from cleanup_exc
        _write_manifest(stage, successful_databases)
        _assert_batch_unchanged(source_state)
        _publish_directory(
            stage,
            destination,
            overwrite,
            destination_state,
        )
        _log_database_summary(
            len(successful_databases),
            len(failures),
            skipped_count,
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


def _inspect_source_databases(
    source: Path,
) -> tuple[_SourceState, list[_SourceDatabase], list[_DatabaseFailure], int]:
    try:
        entries = list(source.iterdir())
        all_databases = sorted(
            (entry for entry in entries if entry.name.endswith(".db")),
            key=lambda entry: entry.name,
        )
    except OSError as exc:
        raise ValidationError(f"无法列出数据库目录：{source}") from exc
    _reject_directory_active_journals(source, entries)
    skipped_gpro_count = sum(
        _is_gpro_database_name(path.name) for path in all_databases
    )
    if skipped_gpro_count:
        logger.warning(
            "跳过已知不兼容的 gpro_v1-6_u_*.db / "
            "en_gpro_v1-6_u_*.db（共 %s 个）",
            skipped_gpro_count,
        )

    databases: list[_SourceDatabase] = []
    failures: list[_DatabaseFailure] = []
    source_entries: list[_SourceEntry] = []
    for path in all_databases:
        try:
            file_stat = path.lstat()
        except OSError as exc:
            if _is_supported_database_name(path.name):
                failures.append(_DatabaseFailure(path.name, "检查", exc))
            continue

        source_entries.append(
            _SourceEntry(
                path=path,
                mode=file_stat.st_mode,
                snapshot=_stat_snapshot(file_stat),
            )
        )
        if not _is_supported_database_name(path.name):
            continue

        try:
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValidationError(
                    f"顶层 .db 项不是普通文件：{path.name}"
                )
            with path.open("rb") as source_file:
                header = source_file.read(QQNT_HEADER_SIZE)
            snapshot = _stat_snapshot(file_stat)
            if header.startswith(SQLITE_HEADER):
                databases.append(_SourceDatabase(path, "plaintext", snapshot))
                continue

            token = _parse_qqnt_header(path, header, file_stat.st_size)
            databases.append(
                _SourceDatabase(path, "encrypted", snapshot, token)
            )
        except Exception as exc:
            failures.append(_DatabaseFailure(path.name, "检查", exc))

    source_state = _SourceState(
        source=source,
        database_names=frozenset(path.name for path in all_databases),
        entries=tuple(source_entries),
    )
    return source_state, databases, failures, skipped_gpro_count


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


def _remove_failed_database_artifacts(output_partial: Path) -> None:
    artifacts = (
        output_partial,
        output_partial.with_name(f"{output_partial.name}-journal"),
        output_partial.with_name(f"{output_partial.name}-wal"),
        output_partial.with_name(f"{output_partial.name}-shm"),
    )
    for artifact in artifacts:
        try:
            artifact.unlink(missing_ok=True)
        except OSError as exc:
            raise PublishError(
                "无法清理失败数据库的暂存文件"
            ) from exc


def _log_database_failure(failure: _DatabaseFailure, uid: str) -> None:
    logger.warning(
        "数据库 %s 处理失败（阶段=%s，类别=%s）：%s",
        _redact_failure_label(failure, uid),
        failure.stage,
        _failure_category(failure.reason),
        _redact_failure_reason(failure, uid),
    )


def _log_database_summary(success: int, failed: int, skipped: int) -> None:
    log = logger.warning if failed or skipped or success == 0 else logger.info
    log(
        "数据库逐库处理汇总：成功 %s 个，失败 %s 个，跳过 %s 个",
        success,
        failed,
        skipped,
    )


def _failure_category(reason: Exception) -> str:
    if isinstance(reason, DependencyError):
        return "依赖不可用"
    if isinstance(reason, ValidationError):
        return "输入校验"
    if isinstance(reason, DatabaseDecryptionError):
        return "数据库解密"
    if isinstance(reason, (OSError, sqlite3.Error)):
        return "文件或数据库I/O"
    return "处理异常"


def _redact_failure_reason(failure: _DatabaseFailure, uid: str) -> str:
    reason = str(failure.reason) or _failure_category(failure.reason)
    safe_name = _redact_failure_label(failure, uid)
    reason = reason.replace(failure.name, safe_name)
    for secret in _failure_secrets(failure, uid):
        if secret:
            reason = reason.replace(secret, "*")
    reason = _UID_FRAGMENT_PATTERN.sub("u_*", reason)
    return _safe_log_text(reason, 320)


def _redact_failure_label(failure: _DatabaseFailure, uid: str) -> str:
    label = failure.name
    for secret in _failure_secrets(failure, uid):
        if secret:
            label = label.replace(secret, "*")
    label = _UID_FRAGMENT_PATTERN.sub("u_*", label)
    return _safe_log_text(label, 120)


def _failure_secrets(failure: _DatabaseFailure, uid: str) -> tuple[str, ...]:
    secrets = [uid, hashlib.md5(uid.encode("utf-8")).hexdigest()]
    if failure.token:
        secrets.extend((failure.token, _derive_key(uid, failure.token)))
    return tuple(secrets)


def _safe_log_text(value: str, limit: int) -> str:
    sanitized = "".join(
        character if character.isprintable() else "?"
        for character in value
    )
    if len(sanitized) <= limit:
        return sanitized
    return f"{sanitized[: limit - 1]}…"


def _assert_batch_unchanged(source_state: _SourceState) -> None:
    _reject_directory_active_journals(source_state.source)
    _assert_database_set_unchanged(source_state)
    for source_entry in source_state.entries:
        try:
            current = source_entry.path.lstat()
        except OSError as exc:
            raise ValidationError(
                "处理期间有源数据库消失或无法读取"
            ) from exc
        if (
            current.st_mode != source_entry.mode
            or _stat_snapshot(current) != source_entry.snapshot
        ):
            raise ValidationError(
                "处理期间有源数据库发生变化"
            )
    _assert_database_set_unchanged(source_state)
    _reject_directory_active_journals(source_state.source)


def _assert_database_set_unchanged(source_state: _SourceState) -> None:
    try:
        current = {
            entry.name
            for entry in source_state.source.iterdir()
            if entry.name.endswith(".db")
        }
    except OSError as exc:
        raise ValidationError("无法重新检查源数据库目录") from exc
    if current != source_state.database_names:
        added = sorted(current - source_state.database_names)
        removed = sorted(source_state.database_names - current)
        changes = []
        if added:
            changes.append(f"新增 {len(added)} 个")
        if removed:
            changes.append(f"移除 {len(removed)} 个")
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
                    f"检测到非空{label}文件；"
                    "请关闭 QQ 后重新复制数据库目录"
                )
        except OSError as exc:
            if is_gpro:
                raise ValidationError(
                    f"无法检查跳过的 gpro 数据库{label}"
                ) from exc
            raise ValidationError(f"无法检查数据库{label}文件") from exc


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
