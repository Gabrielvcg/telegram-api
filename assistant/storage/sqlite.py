import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class SQLiteStorage:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._lock = threading.Lock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    mode TEXT NOT NULL DEFAULT 'normal',
                    profile_summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id)
                );

                CREATE TABLE IF NOT EXISTS agent_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id)
                );

                CREATE TABLE IF NOT EXISTS tool_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    telegram_user_id INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL DEFAULT '{}',
                    output TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES agent_tasks (id),
                    FOREIGN KEY (telegram_user_id) REFERENCES users (telegram_user_id)
                );
                """
            )

    def ensure_user(self, telegram_user_id: int) -> None:
        with self._locked_connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO users (telegram_user_id)
                VALUES (?)
                """,
                (telegram_user_id,),
            )

    def get_mode(self, telegram_user_id: int) -> str:
        self.ensure_user(telegram_user_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT mode FROM users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
        return row["mode"] if row else "normal"

    def set_mode(self, telegram_user_id: int, mode: str) -> None:
        self.ensure_user(telegram_user_id)
        with self._locked_connection() as connection:
            connection.execute(
                """
                UPDATE users
                SET mode = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = ?
                """,
                (mode, telegram_user_id),
            )

    def add_message(self, telegram_user_id: int, role: str, content: str) -> None:
        self.ensure_user(telegram_user_id)
        with self._locked_connection() as connection:
            connection.execute(
                """
                INSERT INTO messages (telegram_user_id, role, content)
                VALUES (?, ?, ?)
                """,
                (telegram_user_id, role, content),
            )

    def get_recent_messages(self, telegram_user_id: int, limit: int) -> list[dict[str, str]]:
        self.ensure_user(telegram_user_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM messages
                WHERE telegram_user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (telegram_user_id, limit),
            ).fetchall()

        return [
            {"role": row["role"], "content": row["content"]}
            for row in reversed(rows)
        ]

    def clear_messages(self, telegram_user_id: int) -> None:
        self.ensure_user(telegram_user_id)
        with self._locked_connection() as connection:
            connection.execute(
                "DELETE FROM messages WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )

    def create_task(
        self,
        telegram_user_id: int,
        kind: str,
        title: str,
        objective: str,
        plan: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        self.ensure_user(telegram_user_id)
        with self._locked_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO agent_tasks
                    (telegram_user_id, kind, status, title, objective, plan, metadata_json)
                VALUES (?, ?, 'pending_approval', ?, ?, ?, ?)
                """,
                (
                    telegram_user_id,
                    kind,
                    title,
                    objective,
                    plan,
                    json.dumps(metadata or {}),
                ),
            )
            return int(cursor.lastrowid)

    def get_task(self, telegram_user_id: int, task_id: int | None = None) -> dict[str, Any] | None:
        self.ensure_user(telegram_user_id)
        with self._connect() as connection:
            if task_id is None:
                row = connection.execute(
                    """
                    SELECT *
                    FROM agent_tasks
                    WHERE telegram_user_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (telegram_user_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT *
                    FROM agent_tasks
                    WHERE telegram_user_id = ? AND id = ?
                    """,
                    (telegram_user_id, task_id),
                ).fetchone()

        return self._task_from_row(row) if row else None

    def list_recent_tasks(self, telegram_user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        self.ensure_user(telegram_user_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM agent_tasks
                WHERE telegram_user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (telegram_user_id, limit),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def update_task_status(self, telegram_user_id: int, task_id: int, status: str) -> bool:
        with self._locked_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = ? AND id = ?
                """,
                (status, telegram_user_id, task_id),
            )
            return cursor.rowcount > 0

    def record_tool_run(
        self,
        telegram_user_id: int,
        tool_name: str,
        status: str,
        input_data: dict[str, Any] | None = None,
        output: str = "",
        task_id: int | None = None,
    ) -> None:
        self.ensure_user(telegram_user_id)
        with self._locked_connection() as connection:
            connection.execute(
                """
                INSERT INTO tool_runs
                    (task_id, telegram_user_id, tool_name, status, input_json, output)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    telegram_user_id,
                    tool_name,
                    status,
                    json.dumps(input_data or {}),
                    output[:4000],
                ),
            )

    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _locked_connection(self):
        return _LockedConnection(self._lock, self._connect())

    def _task_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        task = dict(row)
        task["metadata"] = json.loads(task.pop("metadata_json") or "{}")
        return task


class _LockedConnection:
    def __init__(self, lock: threading.Lock, connection):
        self.lock = lock
        self.connection = connection

    def __enter__(self):
        self.lock.acquire()
        return self.connection.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return self.connection.__exit__(exc_type, exc_value, traceback)
        finally:
            self.lock.release()
