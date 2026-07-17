"""会话内引用关系的唯一性解析。"""

import logging
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from .models import ElementType, ParsedMessage


logger = logging.getLogger(__name__)
REFERENCE_INDEX_BATCH_SIZE = 1000


class ConversationReferenceResolver:
    """用磁盘临时索引把引用 seq 安全解析为平台消息 ID。"""

    def __init__(
        self,
        query,
        conversation_name: str = '',
        batch_size: int = REFERENCE_INDEX_BATCH_SIZE,
    ):
        self.query = query
        self.conversation_name = conversation_name
        self.batch_size = max(1, batch_size)
        self._temp_dir: Optional[TemporaryDirectory] = None
        self._connection: Optional[sqlite3.Connection] = None
        self._index_built = False
        self._closed = False
        self.resolved = 0
        self.ambiguous = 0
        self.missing = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _build_index(self) -> None:
        if self._index_built:
            return

        self._temp_dir = TemporaryDirectory(prefix='qqnt-reference-')
        index_path = Path(self._temp_dir.name) / 'references.sqlite'
        connection = sqlite3.connect(index_path)
        self._connection = connection
        connection.execute('PRAGMA journal_mode=OFF')
        connection.execute('PRAGMA synchronous=OFF')
        connection.execute(
            'CREATE TABLE reference_index ('
            'seq INTEGER PRIMARY KEY, '
            'msg_id TEXT, '
            'matches INTEGER NOT NULL'
            ') WITHOUT ROWID'
        )

        model = self.query.column_descriptions[0]['entity']
        rows = (
            self.query.order_by(None)
            .with_entities(model.seq, model.id)
            .yield_per(self.batch_size)
        )
        statement = (
            'INSERT INTO reference_index(seq, msg_id, matches) VALUES (?, ?, 1) '
            'ON CONFLICT(seq) DO UPDATE SET '
            'msg_id = NULL, matches = reference_index.matches + 1'
        )
        batch = []
        for seq, msg_id in rows:
            if not seq:
                continue
            batch.append((int(seq), str(msg_id)))
            if len(batch) >= self.batch_size:
                connection.executemany(statement, batch)
                batch.clear()
        if batch:
            connection.executemany(statement, batch)
        connection.commit()
        self._index_built = True

    def resolve(self, message: ParsedMessage) -> ParsedMessage:
        """唯一命中时补全引用；直接 ID、歧义和缺失关系保持原状。"""
        if message.quoted_msg_id or not message.quoted_msg_seq:
            return message

        self._build_index()
        row = self._connection.execute(
            'SELECT msg_id, matches FROM reference_index WHERE seq = ?',
            (int(message.quoted_msg_seq),),
        ).fetchone()
        if row is None:
            self.missing += 1
            return message

        target_id, matches = row
        if matches != 1 or not target_id or target_id == message.msg_id:
            self.ambiguous += 1
            return message

        message.quoted_msg_id = str(target_id)
        for element in message.elements:
            if element.type == ElementType.QUOTE:
                element.content['resolved_msg_id'] = message.quoted_msg_id
                break
        self.resolved += 1
        return message

    def close(self) -> None:
        """输出一次汇总并删除临时索引。"""
        if self._closed:
            return
        self._closed = True

        if self.ambiguous or self.missing:
            logger.warning(
                '引用 seq 解析未完全关联: conversation=%r '
                'resolved=%s ambiguous=%s missing=%s',
                self.conversation_name,
                self.resolved,
                self.ambiguous,
                self.missing,
            )
        elif self.resolved:
            logger.info(
                '引用 seq 解析完成: conversation=%r resolved=%s',
                self.conversation_name,
                self.resolved,
            )

        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None
