"""PostgreSQL state for the first auth and project-access slice."""

import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from argon2.exceptions import VerifyMismatchError

from .security import hasher, new_token, token_hash, validate_password

IDLE = timedelta(minutes=15)
ABSOLUTE = timedelta(hours=8)
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_TIME = timedelta(minutes=15)
_DUMMY_HASH = hasher.hash("no-account-password")


def failure_state(count: int, first_failed_at: datetime | None, now: datetime):
    in_window = first_failed_at is not None and first_failed_at > now - FAILURE_WINDOW
    next_count = count + 1 if in_window else 1
    return next_count, first_failed_at if in_window else now, now + LOCK_TIME if next_count >= 5 else None


def session_alive(created_at: datetime, last_seen_at: datetime, now: datetime) -> bool:
    return last_seen_at > now - IDLE and created_at > now - ABSOLUTE


class StoreUnavailable(Exception):
    pass


def _valid_password(stored_hash: str, password: str) -> bool:
    try:
        return hasher.verify(stored_hash, password)
    except VerifyMismatchError:
        return False


class PostgresStore:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL")

    def _connect(self):
        if not self.dsn:
            raise StoreUnavailable("DATABASE_URL is not configured")
        try:
            import psycopg
            from psycopg.rows import dict_row

            return psycopg.connect(self.dsn, row_factory=dict_row)
        except Exception as exc:
            raise StoreUnavailable("PostgreSQL is unavailable") from exc

    def init_schema(self) -> None:
        with self._connect() as conn:
            for statement in Path(__file__).with_name("schema.sql").read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    conn.execute(statement)

    def add_account(self, username: str, password: str) -> None:
        username = username.strip().casefold()
        if not username or len(username) > 80:
            raise ValueError("Username must be 1 to 80 characters")
        with self._connect() as conn:
            names = [row["name"] for row in conn.execute("SELECT name FROM projects")]
            validate_password(password, username, names)
            conn.execute(
                "INSERT INTO accounts (id, username, password_hash) VALUES (%s, %s, %s)",
                (uuid4(), username, hasher.hash(password)),
            )

    def add_project(self, project_id: str, name: str) -> None:
        import re

        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", project_id) or not name.strip():
            raise ValueError("Invalid project id or name")
        with self._connect() as conn:
            conn.execute("INSERT INTO projects (id, name) VALUES (%s, %s)", (project_id, name.strip()))

    def add_member(self, username: str, project_id: str, role: str) -> None:
        if role not in {"Maker", "DataApprover", "SecurityApprover", "Operator", "Auditor"}:
            raise ValueError("Invalid role")
        with self._connect() as conn:
            account = conn.execute("SELECT id FROM accounts WHERE username = %s", (username.strip().casefold(),)).fetchone()
            if not account:
                raise ValueError("Account does not exist")
            conn.execute(
                "INSERT INTO memberships (account_id, project_id, role) VALUES (%s, %s, %s)",
                (account["id"], project_id, role),
            )

    def login(self, username: str, password: str, now: datetime, old_cookie: str | None = None):
        username = username.strip().casefold()
        with self._connect() as conn:
            account = conn.execute(
                "SELECT id, username, password_hash, active, failed_count, first_failed_at, locked_until "
                "FROM accounts WHERE username = %s FOR UPDATE",
                (username,),
            ).fetchone()
            if not account:
                _valid_password(_DUMMY_HASH, password)
                return None
            if not account["active"] or (account["locked_until"] and account["locked_until"] > now):
                _valid_password(_DUMMY_HASH, password)
                return None
            if not _valid_password(account["password_hash"], password):
                count, first, locked = failure_state(account["failed_count"], account["first_failed_at"], now)
                conn.execute(
                    "UPDATE accounts SET failed_count = %s, first_failed_at = %s, locked_until = %s WHERE id = %s",
                    (count, first, locked, account["id"]),
                )
                return None
            conn.execute(
                "UPDATE accounts SET failed_count = 0, first_failed_at = NULL, locked_until = NULL WHERE id = %s",
                (account["id"],),
            )
            if old_cookie:
                conn.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash(old_cookie),))
            cookie, csrf = new_token(), new_token()
            conn.execute(
                "INSERT INTO sessions (token_hash, account_id, csrf_token, created_at, last_seen_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (token_hash(cookie), account["id"], csrf, now, now),
            )
            return {"id": str(account["id"]), "username": account["username"], "csrf_token": csrf, "cookie": cookie}

    def session(self, cookie: str, now: datetime):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT a.id, a.username, s.csrf_token, s.created_at, s.last_seen_at "
                "FROM sessions s JOIN accounts a ON a.id = s.account_id "
                "WHERE s.token_hash = %s AND a.active FOR UPDATE OF s",
                (token_hash(cookie),),
            ).fetchone()
            if not row or not session_alive(row["created_at"], row["last_seen_at"], now):
                return None
            conn.execute("UPDATE sessions SET last_seen_at = %s WHERE token_hash = %s", (now, token_hash(cookie)))
            return {**row, "id": str(row["id"])}

    def logout(self, cookie: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash(cookie),))

    def projects(self, account_id: str):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT p.id, p.name, array_agg(m.role ORDER BY m.role) AS roles "
                "FROM projects p JOIN memberships m ON m.project_id = p.id "
                "WHERE m.account_id = %s GROUP BY p.id, p.name ORDER BY p.id",
                (account_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def project_access(self, account_id: str, project_id: str):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT p.id, p.name, array_agg(m.role ORDER BY m.role) AS roles "
                "FROM projects p JOIN memberships m ON m.project_id = p.id "
                "WHERE m.account_id = %s AND p.id = %s GROUP BY p.id, p.name",
                (account_id, project_id),
            ).fetchone()
            return dict(row) if row else None

    def workbench(self, account_id: str, project_id: str):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT p.id, p.name, m.role FROM projects p "
                "JOIN memberships m ON m.project_id = p.id "
                "JOIN accounts a ON a.id = m.account_id "
                "WHERE m.account_id = %s AND p.id = %s AND a.active "
                "FOR SHARE OF m, a",
                (account_id, project_id),
            ).fetchall()
            if not rows:
                return None
            roles = sorted(row["role"] for row in rows)
            count = None
            if "Maker" in roles:
                count = conn.execute(
                    "SELECT count(*) AS total FROM connections "
                    "WHERE project_id = %s AND state = 'draft_unready'",
                    (project_id,),
                ).fetchone()["total"]
            return {"project": {"id": project_id, "name": rows[0]["name"], "roles": roles}, "draft_unready_count": count}

    @staticmethod
    def _maker(conn, account_id: str, project_id: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM memberships m JOIN accounts a ON a.id = m.account_id "
            "WHERE m.account_id = %s AND m.project_id = %s AND m.role = 'Maker' "
            "AND a.active FOR SHARE OF m, a",
            (account_id, project_id),
        ).fetchone() is not None

    @staticmethod
    def _connection(row):
        return {**row, "id": str(row["id"]), "credential_alias_id": None, "missing_fields": ["credential_alias_id"]}

    def create_connection(self, account_id: str, project_id: str, fields: dict, request_id: str, now: datetime):
        connection_id = uuid4()
        with self._connect() as conn:
            if not self._maker(conn, account_id, project_id):
                return None
            row = conn.execute(
                "INSERT INTO connections (id, project_id, name, kind, host, port, database_name, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (connection_id, project_id, fields["name"], fields["kind"], fields["host"], fields["port"], fields["database_name"], now, now),
            ).fetchone()
            conn.execute(
                "INSERT INTO audit_events (id, project_id, actor_id, action, resource_id, request_id, created_at) "
                "VALUES (%s, %s, %s, 'connection.created', %s, %s, %s)",
                (uuid4(), project_id, account_id, connection_id, request_id, now),
            )
            return self._connection(row)

    def list_connections(self, account_id: str, project_id: str, cursor):
        with self._connect() as conn:
            if not self._maker(conn, account_id, project_id):
                return None
            rows = conn.execute(
                "SELECT * FROM connections WHERE project_id = %s AND (%s::uuid IS NULL OR id > %s::uuid) "
                "ORDER BY id LIMIT 51",
                (project_id, cursor, cursor),
            ).fetchall()
            return {"items": [self._connection(row) for row in rows[:50]], "next_cursor": str(rows[49]["id"]) if len(rows) > 50 else None}

    def get_connection(self, account_id: str, project_id: str, connection_id):
        with self._connect() as conn:
            if not self._maker(conn, account_id, project_id):
                return None
            row = conn.execute(
                "SELECT * FROM connections WHERE id = %s AND project_id = %s",
                (connection_id, project_id),
            ).fetchone()
            return self._connection(row) if row else None

    def update_connection(self, account_id: str, project_id: str, connection_id, fields: dict, request_id: str, now: datetime):
        allowed = {"name", "kind", "host", "port", "database_name"}
        if not fields or not set(fields).issubset(allowed):
            raise ValueError("Invalid connection fields")
        with self._connect() as conn:
            if not self._maker(conn, account_id, project_id):
                return None
            assignments = ", ".join(f"{field} = %s" for field in fields)
            row = conn.execute(
                f"UPDATE connections SET {assignments}, updated_at = %s "
                "WHERE id = %s AND project_id = %s RETURNING *",
                (*fields.values(), now, connection_id, project_id),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "INSERT INTO audit_events (id, project_id, actor_id, action, resource_id, request_id, created_at) "
                "VALUES (%s, %s, %s, 'connection.updated', %s, %s, %s)",
                (uuid4(), project_id, account_id, connection_id, request_id, now),
            )
            return self._connection(row)

    @staticmethod
    def _pipeline(row):
        return {**row, "id": str(row["id"]),
                "source_connection_id": str(row["source_connection_id"]),
                "target_connection_id": str(row["target_connection_id"]),
                "proposed_quality_thresholds": None, "proposed_runtime_budget": None}

    @staticmethod
    def _pipeline_connections_valid(conn, project_id: str, source_id, target_id) -> bool:
        rows = conn.execute(
            "SELECT id, kind FROM connections WHERE project_id = %s AND id IN (%s, %s) FOR SHARE",
            (project_id, source_id, target_id),
        ).fetchall()
        kinds = {row["id"]: row["kind"] for row in rows}
        return kinds.get(source_id) == "mysql_source" and kinds.get(target_id) == "doris_target"

    def create_pipeline(self, account_id: str, project_id: str, fields: dict, request_id: str, now: datetime):
        pipeline_id = uuid4()
        with self._connect() as conn:
            if not self._maker(conn, account_id, project_id) or not self._pipeline_connections_valid(
                conn, project_id, fields["source_connection_id"], fields["target_connection_id"]
            ):
                return None
            row = conn.execute(
                "INSERT INTO pipelines (id, project_id, source_connection_id, target_connection_id, "
                "order_table, user_table, cycle_description, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (pipeline_id, project_id, fields["source_connection_id"], fields["target_connection_id"],
                 fields["order_table"], fields["user_table"], fields["cycle_description"], now, now),
            ).fetchone()
            conn.execute(
                "INSERT INTO audit_events (id, project_id, actor_id, action, resource_id, request_id, created_at) "
                "VALUES (%s, %s, %s, 'pipeline.created', %s, %s, %s)",
                (uuid4(), project_id, account_id, pipeline_id, request_id, now),
            )
            return self._pipeline(row)

    def get_pipeline(self, account_id: str, project_id: str, pipeline_id):
        with self._connect() as conn:
            if not self._maker(conn, account_id, project_id):
                return None
            row = conn.execute(
                "SELECT * FROM pipelines WHERE id = %s AND project_id = %s",
                (pipeline_id, project_id),
            ).fetchone()
            return self._pipeline(row) if row else None

    def update_pipeline(self, account_id: str, project_id: str, pipeline_id, fields: dict, request_id: str, now: datetime):
        allowed = {"source_connection_id", "target_connection_id", "order_table", "user_table", "cycle_description"}
        if not fields or not set(fields).issubset(allowed):
            raise ValueError("Invalid pipeline fields")
        with self._connect() as conn:
            if not self._maker(conn, account_id, project_id):
                return None
            current = conn.execute(
                "SELECT * FROM pipelines WHERE id = %s AND project_id = %s FOR UPDATE",
                (pipeline_id, project_id),
            ).fetchone()
            if not current:
                return None
            source_id = fields.get("source_connection_id", current["source_connection_id"])
            target_id = fields.get("target_connection_id", current["target_connection_id"])
            if not self._pipeline_connections_valid(conn, project_id, source_id, target_id):
                return None
            assignments = ", ".join(f"{field} = %s" for field in fields)
            row = conn.execute(
                f"UPDATE pipelines SET {assignments}, revision = revision + 1, updated_at = %s "
                "WHERE id = %s AND project_id = %s RETURNING *",
                (*fields.values(), now, pipeline_id, project_id),
            ).fetchone()
            conn.execute(
                "INSERT INTO audit_events (id, project_id, actor_id, action, resource_id, request_id, created_at) "
                "VALUES (%s, %s, %s, 'pipeline.updated', %s, %s, %s)",
                (uuid4(), project_id, account_id, pipeline_id, request_id, now),
            )
            return self._pipeline(row)

    def list_audit_events(self, account_id: str, project_id: str, cursor, action, actor_id):
        with self._connect() as conn:
            allowed = conn.execute(
                "SELECT 1 FROM memberships m JOIN accounts a ON a.id = m.account_id "
                "WHERE m.account_id = %s AND m.project_id = %s AND m.role = 'Auditor' "
                "AND a.active FOR SHARE OF m, a",
                (account_id, project_id),
            ).fetchone()
            if not allowed:
                return None
            boundary = None
            if cursor:
                boundary = conn.execute(
                    "SELECT created_at, id FROM audit_events WHERE id = %s AND project_id = %s "
                    "AND action IN ('connection.created', 'connection.updated')",
                    (cursor, project_id),
                ).fetchone()
                if not boundary:
                    raise ValueError("Invalid cursor")
            rows = conn.execute(
                "SELECT id, project_id, actor_id, action, resource_id, request_id, created_at "
                "FROM audit_events WHERE project_id = %s "
                "AND action IN ('connection.created', 'connection.updated') "
                "AND (%s::text IS NULL OR action = %s) "
                "AND (%s::uuid IS NULL OR actor_id = %s) "
                "AND (%s::timestamptz IS NULL OR (created_at, id) < (%s::timestamptz, %s::uuid)) "
                "ORDER BY created_at DESC, id DESC LIMIT 51",
                (project_id, action, action, actor_id, actor_id,
                 boundary["created_at"] if boundary else None,
                 boundary["created_at"] if boundary else None,
                 boundary["id"] if boundary else None),
            ).fetchall()
            items = [{**row, "id": str(row["id"]), "actor_id": str(row["actor_id"]),
                      "resource_id": str(row["resource_id"]), "request_id": str(row["request_id"])} for row in rows[:50]]
            return {"items": items, "next_cursor": str(rows[49]["id"]) if len(rows) > 50 else None}
