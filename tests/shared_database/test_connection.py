from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import anyio

from ai_agent.shared.database.connection import _run_schema_compatibility_migrations


def test_schema_compatibility_migration_adds_agent_rollback_postgres_objects():
    async def run_test():
        class ConnStub:
            dialect = SimpleNamespace(name="postgresql")

            def __init__(self):
                self.statements = []
                self.params = []

            async def execute(self, statement, params=None):
                self.statements.append(str(statement))
                self.params.append(params or {})

        conn = ConnStub()

        await _run_schema_compatibility_migrations(conn)

        assert any("ADD COLUMN IF NOT EXISTS nono_state_home" in statement for statement in conn.statements)
        assert any("SET nono_state_home" in statement for statement in conn.statements)
        assert any("WHERE status = 'publishing'" in statement for statement in conn.statements)
        assert any(
            params.get("reason") == "duplicate active rollback isolated during schema migration"
            for params in conn.params
        )

    anyio.run(run_test)


def test_schema_compatibility_migration_skips_existing_sqlite_column():
    async def run_test():
        class ConnStub:
            dialect = SimpleNamespace(name="sqlite")

            def __init__(self):
                self.statements = []

            async def execute(self, statement, params=None):
                self.statements.append(str(statement))
                if str(statement).startswith("PRAGMA table_info"):
                    return [(0, "nono_state_home")]
                return []

        conn = ConnStub()

        await _run_schema_compatibility_migrations(conn)

        assert not any("ADD COLUMN nono_state_home" in statement for statement in conn.statements)

    anyio.run(run_test)


def test_schema_compatibility_migration_is_idempotent_for_isolated_duplicates():
    async def run_test():
        class SqliteConn:
            dialect = SimpleNamespace(name="sqlite")

            def __init__(self):
                self.db = sqlite3.connect(":memory:")
                self.db.row_factory = sqlite3.Row

            async def execute(self, statement, params=None):
                cursor = self.db.execute(str(statement), params or {})
                self.db.commit()
                return cursor.fetchall()

        conn = SqliteConn()
        conn.db.executescript(
            """
            CREATE TABLE agent_rollbacks (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                nono_session_id TEXT NOT NULL,
                snapshot INTEGER NOT NULL DEFAULT 0,
                nono_state_home TEXT NOT NULL DEFAULT '',
                requested_by TEXT NOT NULL,
                status TEXT NOT NULL,
                command_results TEXT,
                error_message TEXT,
                requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            );
            INSERT INTO agent_rollbacks
                (id, run_id, nono_session_id, snapshot, nono_state_home, requested_by, status, requested_at)
            VALUES
                ('rollback-queued', 'run-1', 'nono-1', 0, '/state/run-1', 'user', 'queued', '2026-07-13 01:00:00'),
                ('rollback-requested', 'run-1', 'nono-1', 0, '/state/run-1', 'user', 'requested', '2026-07-13 02:00:00');
            """
        )

        await _run_schema_compatibility_migrations(conn)
        await _run_schema_compatibility_migrations(conn)

        rows = conn.db.execute(
            "SELECT id, status, error_message FROM agent_rollbacks ORDER BY id"
        ).fetchall()

        assert [(row["id"], row["status"]) for row in rows] == [
            ("rollback-queued", "queued"),
            ("rollback-requested", "failed"),
        ]
        assert rows[1]["error_message"] == "duplicate active rollback isolated during schema migration"

    anyio.run(run_test)
