from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from friday.models import Conversation, Message


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LocalStore:
    """SQLite-only persistence. No account, cloud database, or telemetry."""

    def __init__(self, database: Path) -> None:
        self.database = database
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        """Commit and close every SQLite connection (important on Windows)."""
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, model TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    web_enabled INTEGER NOT NULL DEFAULT 0,
                    memory_enabled INTEGER NOT NULL DEFAULT 1,
                    incognito INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL,
                    created_at TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, content TEXT NOT NULL, source TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                """
            )
            # Local, additive migration for existing Friday databases.
            existing = {row["name"] for row in db.execute("PRAGMA table_info(conversations)")}
            for column, definition in (
                ("web_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("memory_enabled", "INTEGER NOT NULL DEFAULT 1"),
                ("incognito", "INTEGER NOT NULL DEFAULT 0"),
                ("pinned", "INTEGER NOT NULL DEFAULT 0"),
                ("archived", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if column not in existing:
                    db.execute(f"ALTER TABLE conversations ADD COLUMN {column} {definition}")
            try:
                db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(content, memory_id UNINDEXED)")
            except sqlite3.OperationalError:
                pass

    def setting(self, key: str, default: object = None) -> object:
        with self._connection() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: object) -> None:
        payload = json.dumps(value)
        with self._connection() as db:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, payload))

    def new_conversation(self, model: str = "Friday Auto", web_enabled: bool = False, memory_enabled: bool = True, incognito: bool = False) -> Conversation:
        created = now()
        conversation = Conversation(str(uuid.uuid4()), "New conversation", model, created, created, "", web_enabled, memory_enabled, incognito)
        with self._connection() as db:
            db.execute(
                """INSERT INTO conversations
                (id,title,model,created_at,updated_at,summary,web_enabled,memory_enabled,incognito,pinned,archived)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (conversation.id, conversation.title, conversation.model, conversation.created_at, conversation.updated_at,
                 conversation.summary, int(conversation.web_enabled), int(conversation.memory_enabled),
                 int(conversation.incognito), int(conversation.pinned), int(conversation.archived)),
            )
        return conversation

    def conversations(self, query: str = "", include_archived: bool = False) -> list[Conversation]:
        with self._connection() as db:
            archive_clause = "" if include_archived else "archived=0 AND "
            if query.strip():
                rows = db.execute(
                    f"SELECT * FROM conversations WHERE {archive_clause}(title LIKE ? OR id IN (SELECT conversation_id FROM messages WHERE content LIKE ?)) ORDER BY pinned DESC, updated_at DESC",
                    (f"%{query.strip()}%", f"%{query.strip()}%"),
                ).fetchall()
            else:
                rows = db.execute(f"SELECT * FROM conversations WHERE {archive_clause}1=1 ORDER BY pinned DESC, updated_at DESC").fetchall()
        return [Conversation(**dict(row)) for row in rows]

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        return Conversation(**dict(row)) if row else None

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        with self._connection() as db:
            db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title[:80], now(), conversation_id))

    def clear_messages(self, conversation_id: str) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
            db.execute("UPDATE conversations SET summary='', updated_at=? WHERE id=?", (now(), conversation_id))

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))

    def set_model(self, conversation_id: str, model: str) -> None:
        with self._connection() as db:
            db.execute("UPDATE conversations SET model=?, updated_at=? WHERE id=?", (model, now(), conversation_id))

    def set_conversation_options(self, conversation_id: str, *, web_enabled: bool | None = None,
                                 memory_enabled: bool | None = None, incognito: bool | None = None) -> None:
        changes = {"web_enabled": web_enabled, "memory_enabled": memory_enabled, "incognito": incognito}
        updates = [(key, int(value)) for key, value in changes.items() if value is not None]
        if not updates:
            return
        fields = ", ".join(f"{key}=?" for key, _value in updates)
        with self._connection() as db:
            db.execute(f"UPDATE conversations SET {fields}, updated_at=? WHERE id=?", (*[value for _key, value in updates], now(), conversation_id))

    def set_pinned(self, conversation_id: str, pinned: bool) -> None:
        with self._connection() as db:
            db.execute("UPDATE conversations SET pinned=?, updated_at=? WHERE id=?", (int(pinned), now(), conversation_id))

    def set_archived(self, conversation_id: str, archived: bool) -> None:
        with self._connection() as db:
            db.execute("UPDATE conversations SET archived=?, updated_at=? WHERE id=?", (int(archived), now(), conversation_id))

    def save_message(self, conversation_id: str, role: str, content: str, metadata: dict | None = None) -> Message:
        message = Message(str(uuid.uuid4()), conversation_id, role, content, now(), json.dumps(metadata or {}))
        with self._connection() as db:
            db.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?)",
                (message.id, message.conversation_id, message.role, message.content, message.created_at, message.metadata),
            )
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id))
        return message

    def messages(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        statement = "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at"
        params: tuple = (conversation_id,)
        if limit:
            statement = "SELECT * FROM (" + statement + " DESC LIMIT ?) ORDER BY created_at"
            params = (conversation_id, limit)
        with self._connection() as db:
            rows = db.execute(statement, params).fetchall()
        return [Message(**dict(row)) for row in rows]

    def delete_last_assistant_message(self, conversation_id: str) -> bool:
        with self._connection() as db:
            row = db.execute("SELECT id FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY created_at DESC LIMIT 1", (conversation_id,)).fetchone()
            if not row:
                return False
            db.execute("DELETE FROM messages WHERE id=?", (row["id"],))
        return True

    def update_summary(self, conversation_id: str, summary: str) -> None:
        with self._connection() as db:
            db.execute("UPDATE conversations SET summary=? WHERE id=?", (summary[:4000], conversation_id))

    def remember(self, content: str, source: str = "user") -> None:
        memory_id = str(uuid.uuid4())
        timestamp = now()
        with self._connection() as db:
            db.execute("INSERT INTO memories VALUES(?,?,?,?,?)", (memory_id, content[:2000], source, timestamp, timestamp))
            try:
                db.execute("INSERT INTO memory_search(content,memory_id) VALUES(?,?)", (content[:2000], memory_id))
            except sqlite3.OperationalError:
                pass

    # Alias so ToolEngine can call store.save_memory(...)
    def save_memory(self, content: str, category: str = "USER") -> None:
        self.remember(content, category.upper())


    def get_memory_stats(self) -> dict:
        with self._connection() as db:
            total = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            rows = db.execute("SELECT source, COUNT(*) FROM memories GROUP BY source").fetchall()
            categories = {row["source"]: row[1] for row in rows}
            return {"total": total, "categories": categories}
    def all_memories(self) -> list[str]:
        """Return all stored memories, newest first."""
        with self._connection() as db:
            rows = db.execute("SELECT content FROM memories ORDER BY updated_at DESC").fetchall()
        return [row["content"] for row in rows]

    def delete_memories_matching(self, keyword: str) -> int:
        """Delete all memories that contain the given keyword. Returns count deleted."""
        pattern = f"%{keyword}%"
        with self._connection() as db:
            rows = db.execute("SELECT id FROM memories WHERE content LIKE ?", (pattern,)).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                placeholders = ",".join("?" * len(ids))
                db.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", ids)
                try:
                    db.execute(f"DELETE FROM memory_search WHERE memory_id IN ({placeholders})", ids)
                except sqlite3.OperationalError:
                    pass
        return len(ids)

    def relevant_memories(self, query: str, limit: int = 4) -> list[str]:
        terms = " ".join(word for word in query.replace("'", " ").split() if len(word) > 2)[:180]
        if not terms:
            return []
        with self._connection() as db:
            try:
                rows = db.execute("SELECT m.content FROM memory_search s JOIN memories m ON m.id=s.memory_id WHERE memory_search MATCH ? LIMIT ?", (terms, limit)).fetchall()
            except sqlite3.OperationalError:
                rows = db.execute("SELECT content FROM memories WHERE content LIKE ? ORDER BY updated_at DESC LIMIT ?", (f"%{terms.split()[0]}%", limit)).fetchall()
        return [row["content"] for row in rows]
