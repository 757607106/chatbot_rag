"""多知识库定义的 SQLite 注册表。"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, TypeVar, cast

from chatbot_rag.rag.knowledge_catalog import (
    CatalogConflictError,
    CatalogNotFoundError,
)

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class KnowledgeBaseRecord:
    """一个逻辑知识库及其独立物理资源绑定。"""

    knowledge_base_id: str
    name: str
    description: str
    collection_name: str
    documents_path: Path
    is_default: bool
    created_at: str
    updated_at: str


class KnowledgeBaseRegistry:
    """通过短连接事务维护知识库注册信息。"""

    def __init__(self, path: Path) -> None:
        """使用与文档目录共享的 SQLite 数据库。"""
        self._path = path

    async def initialize(self) -> None:
        """创建知识库注册表。"""
        await self._call(self._initialize_sync)

    async def ensure_default(
        self,
        *,
        knowledge_base_id: str,
        knowledge_base_name: str,
        description: str,
        collection_name: str,
        documents_path: Path,
    ) -> KnowledgeBaseRecord:
        """登记兼容既有部署的默认知识库。"""
        return await self._call(
            self._ensure_default_sync,
            knowledge_base_id,
            knowledge_base_name,
            description,
            collection_name,
            documents_path,
        )

    async def list_knowledge_bases(self) -> list[KnowledgeBaseRecord]:
        """列出全部知识库，默认知识库始终排在最前。"""
        return await self._call(self._list_knowledge_bases_sync)

    async def get_knowledge_base(
        self,
        knowledge_base_id: str,
    ) -> KnowledgeBaseRecord:
        """读取一个知识库。"""
        return await self._call(
            self._get_knowledge_base_sync,
            knowledge_base_id,
        )

    async def create_knowledge_base(
        self,
        *,
        name: str,
        description: str,
        documents_root: Path,
    ) -> KnowledgeBaseRecord:
        """创建使用独立目录和 Qdrant collection 的知识库。"""
        return await self._call(
            self._create_knowledge_base_sync,
            name,
            description,
            documents_root,
        )

    async def delete_knowledge_base(
        self,
        knowledge_base_id: str,
    ) -> None:
        """删除一个非默认知识库的注册记录。

        Raises:
            CatalogNotFoundError: 知识库不存在时抛出。
            CatalogConflictError: 试图删除默认知识库时抛出。
        """
        await self._call(
            self._delete_knowledge_base_sync,
            knowledge_base_id,
        )

    async def _call(
        self,
        operation: Callable[..., _T],
        *args: object,
    ) -> _T:
        """在线程中执行短生命周期 SQLite 操作。"""
        return await asyncio.to_thread(operation, *args)

    def _delete_knowledge_base_sync(self, knowledge_base_id: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT is_default FROM knowledge_bases
                WHERE knowledge_base_id = ?
                """,
                (knowledge_base_id,),
            ).fetchone()
        if row is None:
            raise CatalogNotFoundError("知识库不存在。")
        if row["is_default"]:
            raise CatalogConflictError("默认知识库不能删除。")
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM knowledge_bases
                WHERE knowledge_base_id = ?
                """,
                (knowledge_base_id,),
            )
            connection.commit()

    def _initialize_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._migrate_drop_tenant_id(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    knowledge_base_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    collection_name TEXT NOT NULL UNIQUE,
                    documents_path TEXT NOT NULL UNIQUE,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_bases_created
                    ON knowledge_bases(is_default DESC, created_at ASC);
                """,
            )

    def _migrate_drop_tenant_id(self, connection: sqlite3.Connection) -> None:
        """将旧多租户 schema 迁移为当前无 tenant_id 的结构。"""
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(knowledge_bases)",
            ).fetchall()
        }
        if "tenant_id" not in columns:
            return
        connection.executescript(
            """
            CREATE TABLE knowledge_bases_migrated (
                knowledge_base_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                collection_name TEXT NOT NULL UNIQUE,
                documents_path TEXT NOT NULL UNIQUE,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO knowledge_bases_migrated (
                knowledge_base_id, name, normalized_name,
                description, collection_name, documents_path,
                is_default, created_at, updated_at
            )
            SELECT
                knowledge_base_id, name, normalized_name,
                description, collection_name, documents_path,
                is_default, created_at, updated_at
            FROM knowledge_bases;
            DROP TABLE knowledge_bases;
            ALTER TABLE knowledge_bases_migrated
                RENAME TO knowledge_bases;
            CREATE INDEX IF NOT EXISTS idx_knowledge_bases_created
                ON knowledge_bases(is_default DESC, created_at ASC);
            DROP TABLE IF EXISTS knowledge_tenants;
            """,
        )

    def _ensure_default_sync(
        self,
        knowledge_base_id: str,
        knowledge_base_name: str,
        description: str,
        collection_name: str,
        documents_path: Path,
    ) -> KnowledgeBaseRecord:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_bases (
                    knowledge_base_id, name, normalized_name,
                    description, collection_name, documents_path,
                    is_default, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(knowledge_base_id) DO UPDATE SET
                    collection_name = excluded.collection_name,
                    documents_path = excluded.documents_path,
                    is_default = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    knowledge_base_id,
                    knowledge_base_name,
                    _normalize_name(knowledge_base_name),
                    description,
                    collection_name,
                    str(documents_path),
                    now,
                    now,
                ),
            )
            connection.commit()
        return self._get_knowledge_base_sync(knowledge_base_id)

    def _list_knowledge_bases_sync(self) -> list[KnowledgeBaseRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM knowledge_bases
                ORDER BY is_default DESC, created_at ASC
                """,
            ).fetchall()
        return [_knowledge_base_from_row(row) for row in rows]

    def _get_knowledge_base_sync(
        self,
        knowledge_base_id: str,
    ) -> KnowledgeBaseRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_bases
                WHERE knowledge_base_id = ?
                """,
                (knowledge_base_id,),
            ).fetchone()
        if row is None:
            raise CatalogNotFoundError("知识库不存在。")
        return _knowledge_base_from_row(row)

    def _create_knowledge_base_sync(
        self,
        name: str,
        description: str,
        documents_root: Path,
    ) -> KnowledgeBaseRecord:
        knowledge_base_id = f"kb_{uuid.uuid4().hex}"
        documents_path = documents_root / knowledge_base_id
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO knowledge_bases (
                        knowledge_base_id, name, normalized_name,
                        description, collection_name, documents_path,
                        is_default, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        knowledge_base_id,
                        name,
                        _normalize_name(name),
                        description,
                        knowledge_base_id,
                        str(documents_path),
                        now,
                        now,
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError as error:
            raise CatalogConflictError("同名知识库已经存在。") from error
        return self._get_knowledge_base_sync(knowledge_base_id)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """创建、配置并确保关闭一个短生命周期连接。"""
        connection = sqlite3.connect(self._path, timeout=30.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
        finally:
            connection.close()


def _knowledge_base_from_row(row: sqlite3.Row) -> KnowledgeBaseRecord:
    return KnowledgeBaseRecord(
        knowledge_base_id=cast(str, row["knowledge_base_id"]),
        name=cast(str, row["name"]),
        description=cast(str, row["description"]),
        collection_name=cast(str, row["collection_name"]),
        documents_path=Path(cast(str, row["documents_path"])),
        is_default=bool(row["is_default"]),
        created_at=cast(str, row["created_at"]),
        updated_at=cast(str, row["updated_at"]),
    )


def _normalize_name(value: str) -> str:
    """生成用于知识库名称唯一约束的稳定键。"""
    return value.strip().casefold()


def _now() -> str:
    """返回可按字符串排序的 UTC 时间。"""
    return datetime.now(UTC).isoformat()
