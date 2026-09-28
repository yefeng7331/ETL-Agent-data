import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from etl_agent.app import create_app
from etl_agent.db import failure_state, session_alive
from etl_agent.security import hasher, token_hash, validate_password

PASSWORD = "A private passphrase with several words"
START = datetime(2026, 9, 28, tzinfo=timezone.utc)


class FakeStore:
    """Exercises HTTP boundaries; PostgreSQL integration remains separate."""

    def __init__(self):
        self.sessions = {}
        self.member_of_alpha = True
        self.fail_count = 0
        self.first_failed = None
        self.locked_until = None
        self.calls = []
        self.roles = ["Maker"]
        self.connections = {}
        self.pipelines = {}
        self.audit_events = []

    def login(self, username, password, now, old_cookie=None):
        self.calls.append(("login", username))
        if username != "alice" or (self.locked_until and now < self.locked_until):
            return None
        if password != PASSWORD:
            self.fail_count, self.first_failed, self.locked_until = failure_state(self.fail_count, self.first_failed, now)
            return None
        self.fail_count, self.first_failed, self.locked_until = 0, None, None
        if old_cookie:
            self.sessions.pop(token_hash(old_cookie), None)
        cookie, csrf = "session-secret-value", "csrf-secret-value"
        self.sessions[token_hash(cookie)] = (now, now, csrf)
        return {"id": "account-1", "username": "alice", "csrf_token": csrf, "cookie": cookie}

    def session(self, cookie, now):
        state = self.sessions.get(token_hash(cookie))
        if not state or not session_alive(state[0], state[1], now):
            return None
        self.sessions[token_hash(cookie)] = (state[0], now, state[2])
        return {"id": "account-1", "username": "alice", "csrf_token": state[2]}

    def logout(self, cookie):
        self.sessions.pop(token_hash(cookie), None)

    def projects(self, account_id):
        self.calls.append(("projects", account_id))
        return [{"id": "alpha", "name": "Alpha", "roles": ["Maker"]}] if self.member_of_alpha else []

    def project_access(self, account_id, project_id):
        self.calls.append(("access", account_id, project_id))
        return {"id": "alpha", "name": "Alpha", "roles": self.roles} if self.member_of_alpha and project_id == "alpha" else None

    def workbench(self, account_id, project_id):
        project = self.project_access(account_id, project_id)
        if not project:
            return None
        count = len(self.connections) if "Maker" in self.roles else None
        return {"project": project, "draft_unready_count": count}

    def create_connection(self, account_id, project_id, fields, request_id, now):
        if not self.member_of_alpha or "Maker" not in self.roles or project_id != "alpha":
            return None
        connection_id = str(uuid4())
        row = {**fields, "id": connection_id, "project_id": project_id, "state": "draft_unready", "credential_alias_id": None, "missing_fields": ["credential_alias_id"], "created_at": now, "updated_at": now}
        self.connections[connection_id] = row
        self.audit_events.append({"id": str(uuid4()), "project_id": project_id, "actor_id": account_id, "action": "connection.created", "resource_id": connection_id, "request_id": request_id, "created_at": now})
        return row

    def list_connections(self, account_id, project_id, cursor):
        if not self.member_of_alpha or "Maker" not in self.roles or project_id != "alpha":
            return None
        rows = [self.connections[key] for key in sorted(self.connections) if cursor is None or key > str(cursor)]
        return {"items": rows[:50], "next_cursor": rows[49]["id"] if len(rows) > 50 else None}

    def get_connection(self, account_id, project_id, connection_id):
        if not self.member_of_alpha or "Maker" not in self.roles or project_id != "alpha":
            return None
        return self.connections.get(str(connection_id))

    def update_connection(self, account_id, project_id, connection_id, fields, request_id, now):
        row = self.get_connection(account_id, project_id, connection_id)
        if not row:
            return None
        row.update(fields)
        row["updated_at"] = now
        self.audit_events.append({"id": str(uuid4()), "project_id": project_id, "actor_id": account_id, "action": "connection.updated", "resource_id": str(connection_id), "request_id": request_id, "created_at": now})
        return row

    def _valid_pipeline_connections(self, project_id, fields):
        source = self.connections.get(str(fields["source_connection_id"]))
        target = self.connections.get(str(fields["target_connection_id"]))
        return (source and target and source["project_id"] == target["project_id"] == project_id
                and source["kind"] == "mysql_source" and target["kind"] == "doris_target")

    def create_pipeline(self, account_id, project_id, fields, request_id, now):
        if not self.member_of_alpha or "Maker" not in self.roles or project_id != "alpha" or not self._valid_pipeline_connections(project_id, fields):
            return None
        pipeline_id = str(uuid4())
        row = {**fields, "source_connection_id": str(fields["source_connection_id"]), "target_connection_id": str(fields["target_connection_id"]),
               "id": pipeline_id, "project_id": project_id, "state": "draft_unready", "revision": 1,
               "proposed_quality_thresholds": None, "proposed_runtime_budget": None,
               "created_at": now, "updated_at": now}
        self.pipelines[pipeline_id] = row
        self.audit_events.append({"id": str(uuid4()), "project_id": project_id, "actor_id": account_id, "action": "pipeline.created", "resource_id": pipeline_id, "request_id": request_id, "created_at": now})
        return row

    def get_pipeline(self, account_id, project_id, pipeline_id):
        if not self.member_of_alpha or "Maker" not in self.roles or project_id != "alpha":
            return None
        return self.pipelines.get(str(pipeline_id))

    def update_pipeline(self, account_id, project_id, pipeline_id, fields, request_id, now):
        row = self.get_pipeline(account_id, project_id, pipeline_id)
        if not row:
            return None
        updated = {**row, **fields}
        if not self._valid_pipeline_connections(project_id, updated):
            return None
        row.update(fields)
        row["source_connection_id"] = str(row["source_connection_id"])
        row["target_connection_id"] = str(row["target_connection_id"])
        row["revision"] += 1
        row["updated_at"] = now
        self.audit_events.append({"id": str(uuid4()), "project_id": project_id, "actor_id": account_id, "action": "pipeline.updated", "resource_id": str(pipeline_id), "request_id": request_id, "created_at": now})
        return row

    def list_audit_events(self, account_id, project_id, cursor, action, actor_id):
        if not self.member_of_alpha or "Auditor" not in self.roles or project_id != "alpha":
            return None
        rows = sorted((row for row in self.audit_events if row["project_id"] == project_id and row["action"] in {"connection.created", "connection.updated"} and (action is None or row["action"] == action) and (actor_id is None or row["actor_id"] == str(actor_id))), key=lambda row: (row["created_at"], row["id"]), reverse=True)
        if cursor:
            boundary = next((row for row in self.audit_events if row["id"] == str(cursor) and row["project_id"] == project_id), None)
            if boundary is None:
                raise ValueError("Invalid cursor")
            rows = [row for row in rows if (row["created_at"], row["id"]) < (boundary["created_at"], boundary["id"])]
        return {"items": rows[:50], "next_cursor": rows[49]["id"] if len(rows) > 50 else None}


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.now = START
        self.client = TestClient(create_app(self.store, lambda: self.now), base_url="https://testserver", raise_server_exceptions=False)

    def login(self):
        return self.client.post("/api/v1/session", json={"username": "alice", "password": PASSWORD})

    def test_login_project_scope_csrf_logout_and_no_secret_echo(self):
        self.assertEqual(self.client.get("/api/v1/projects").status_code, 401)
        login = self.login()
        self.assertEqual(login.status_code, 200)
        self.assertNotIn(PASSWORD, login.text)
        self.assertNotIn("session-secret-value", login.text)
        cookie = login.headers["set-cookie"]
        for flag in ("httponly", "secure", "samesite=lax"):
            self.assertIn(flag, cookie.lower())
        self.assertEqual([p["id"] for p in self.client.get("/api/v1/projects").json()["items"]], ["alpha"])
        self.assertEqual(self.client.get("/api/v1/projects/alpha/access").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/projects/beta/access").status_code, 404)
        self.assertIn(("access", "account-1", "beta"), self.store.calls)
        self.store.member_of_alpha = False
        self.assertEqual(self.client.get("/api/v1/projects/alpha/access").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/projects").json()["items"], [])
        self.assertEqual(self.client.delete("/api/v1/session").status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/session", headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/session", headers={"X-CSRF-Token": login.json()["csrf_token"], "Origin": "https://attacker.example"}).status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/session", headers={"X-CSRF-Token": login.json()["csrf_token"]}).status_code, 204)
        self.assertEqual(self.client.get("/api/v1/projects").status_code, 401)

    def test_lock_after_five_failures_and_reset_after_expiry(self):
        for _ in range(5):
            result = self.client.post("/api/v1/session", json={"username": "alice", "password": "wrong"})
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.json()["error"]["message"], "Invalid credentials")
        self.assertEqual(self.login().status_code, 401)
        unknown = self.client.post("/api/v1/session", json={"username": "unknown", "password": "wrong"})
        self.assertEqual(unknown.json()["error"]["message"], "Invalid credentials")
        self.now += timedelta(minutes=15)
        self.assertEqual(self.login().status_code, 200)

    def test_session_idle_and_absolute_boundaries(self):
        self.assertTrue(session_alive(START, START, START + timedelta(minutes=14, seconds=59)))
        self.assertFalse(session_alive(START, START, START + timedelta(minutes=15)))
        self.assertFalse(session_alive(START, START + timedelta(hours=7, minutes=59), START + timedelta(hours=8)))
        self.login()
        self.now += timedelta(minutes=15)
        self.assertEqual(self.client.get("/api/v1/session").status_code, 401)

    def test_origin_and_input_error_do_not_echo_password(self):
        result = self.client.post("/api/v1/session", json={"username": "alice", "password": PASSWORD}, headers={"Origin": "https://attacker.example"})
        self.assertEqual(result.status_code, 403)
        result = self.client.post("/api/v1/session", json={"username": "alice", "password": {"secret": PASSWORD}})
        self.assertEqual(result.status_code, 400)
        self.assertNotIn(PASSWORD, result.text)

    def test_openapi_and_https_boundary(self):
        schema = self.client.get("/openapi.json").json()
        self.assertEqual(schema["openapi"], "3.1.0")
        paths = schema["paths"]
        self.assertEqual(set(paths), {
            "/api/v1/session", "/api/v1/projects", "/api/v1/projects/{project_id}/access",
            "/api/v1/projects/{project_id}/connections",
            "/api/v1/projects/{project_id}/connections/{connection_id}",
            "/api/v1/projects/{project_id}/connections/{connection_id}/probes",
            "/api/v1/projects/{project_id}/workbench",
            "/api/v1/projects/{project_id}/audit-events",
            "/api/v1/projects/{project_id}/pipelines",
            "/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
        })
        names = {item["name"] for item in paths["/api/v1/session"]["delete"]["parameters"]}
        self.assertEqual(names, {"etl_session", "x-csrf-token"})
        self.assertIn("400", paths["/api/v1/session"]["post"]["responses"])
        self.assertNotIn("422", paths["/api/v1/session"]["post"]["responses"])
        probe_responses = paths["/api/v1/projects/{project_id}/connections/{connection_id}/probes"]["post"]["responses"]
        self.assertIn("422", probe_responses)
        self.assertNotIn("200", probe_responses)
        self.assertEqual(probe_responses["422"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/ErrorOut")
        with TestClient(create_app(self.store, lambda: self.now), base_url="http://testserver") as client:
            self.assertEqual(client.post("/api/v1/session", json={"username": "alice", "password": PASSWORD}).json()["error"]["code"], "HTTPS_REQUIRED")

    def test_password_policy(self):
        with self.assertRaises(ValueError):
            validate_password("too-short", "alice", ["Alpha"])
        with self.assertRaises(ValueError):
            validate_password("A-very-long-alice-passphrase", "alice", ["Alpha"])
        with self.assertRaises(ValueError):
            validate_password("asdfghjklzxcvbnm", "alice", ["Alpha"])
        validate_password("A private passphrase with several words" + "x" * 40, "alice", ["Alpha"])
        encoded = hasher.hash(PASSWORD)
        self.assertNotIn(PASSWORD, encoded)
        self.assertTrue(hasher.verify(encoded, PASSWORD))
        self.assertNotEqual(token_hash("session-secret-value"), "session-secret-value")

    def test_workbench_only_shows_available_project_data(self):
        path = "/api/v1/projects/alpha/workbench"
        self.assertEqual(self.client.get(path).status_code, 401)
        login = self.login()
        self.assertEqual(self.client.get(path.replace("alpha", "beta")).status_code, 404)
        empty = self.client.get(path).json()
        self.assertEqual(empty["project"]["id"], "alpha")
        self.assertEqual(empty["connections"]["draft_unready_count"], 0)
        self.assertEqual(empty["connections"]["href"], "/api/v1/projects/alpha/connections")
        self.assertEqual(set(empty["allowed_actions"]), {"project.read", "workbench.read", "connections.read", "connections.create", "connections.update"})
        self.assertEqual(set(empty["unavailable_sections"]), {"pipelines", "preparations", "runs", "inbox"})
        fields = {"name": "Order source", "kind": "mysql_source", "host": "mysql.internal", "port": 3306, "database_name": "orders"}
        self.assertEqual(self.client.post("/api/v1/projects/alpha/connections", json=fields, headers={"X-CSRF-Token": login.json()["csrf_token"]}).status_code, 201)
        self.assertEqual(self.client.get(path).json()["connections"]["draft_unready_count"], 1)
        self.store.roles = ["Auditor"]
        auditor = self.client.get(path)
        self.assertEqual(auditor.status_code, 200)
        self.assertIsNone(auditor.json()["connections"])
        self.assertEqual(auditor.json()["allowed_actions"], ["project.read", "workbench.read", "audit_events.read"])
        self.assertNotIn("mysql.internal", auditor.text)
        self.assertNotIn("draft_unready_count", auditor.text)
        self.store.member_of_alpha = False
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_unready_connection_draft_scope_audit_and_probe_block(self):
        login = self.login()
        csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        base = "/api/v1/projects/alpha/connections"
        fields = {"name": "Order source", "kind": "mysql_source", "host": "mysql.internal", "port": 3306, "database_name": "orders"}
        self.assertEqual(self.client.post(base, json=fields).status_code, 403)
        secret_rejected = self.client.post(base, json={**fields, "password": "sensitive"}, headers=csrf)
        self.assertEqual(secret_rejected.status_code, 400)
        self.assertNotIn("sensitive", secret_rejected.text)
        self.assertEqual(self.client.post(base, json={**fields, "host": "https://secret@example.test"}, headers=csrf).status_code, 400)
        self.assertEqual(self.client.post(base.replace("alpha", "beta"), json=fields, headers=csrf).status_code, 404)
        created = self.client.post(base, json=fields, headers=csrf)
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual(body["state"], "draft_unready")
        self.assertEqual(body["missing_fields"], ["credential_alias_id"])
        self.assertIsNone(body["credential_alias_id"])
        self.assertNotIn("password", created.text)
        self.assertEqual(self.store.audit_events[0]["request_id"], created.headers["x-request-id"])
        url = f"{base}/{body['id']}"
        self.assertEqual(self.client.get(base).json()["items"][0]["id"], body["id"])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url.replace("alpha", "beta")).status_code, 404)
        self.assertEqual(self.client.post(url + "/probes", headers=csrf).json()["error"]["code"], "SECRET_ALIAS_UNAVAILABLE")
        changed = self.client.patch(url, json={"host": "new.internal"}, headers=csrf)
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["host"], "new.internal")
        self.assertEqual(len(self.store.audit_events), 2)
        self.store.roles = ["Auditor"]
        self.assertEqual(self.client.get(base).status_code, 403)
        self.assertEqual(self.client.patch(url, json={"name": "Other"}, headers=csrf).status_code, 403)
        self.store.member_of_alpha = False
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_auditor_connection_events_scope_filters_and_cursor(self):
        base = "/api/v1/projects/alpha/audit-events"
        self.assertEqual(self.client.get(base).status_code, 401)
        login = self.login()
        self.assertEqual(self.client.get(base).status_code, 403)
        csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        fields = {"name": "Order source", "kind": "mysql_source", "host": "mysql.internal", "port": 3306, "database_name": "orders"}
        created = self.client.post("/api/v1/projects/alpha/connections", json=fields, headers=csrf).json()
        self.client.patch(f"/api/v1/projects/alpha/connections/{created['id']}", json={"host": "new.internal"}, headers=csrf)
        self.store.audit_events.append({**self.store.audit_events[0], "id": str(uuid4()), "project_id": "beta"})
        self.store.audit_events.append({**self.store.audit_events[0], "id": str(uuid4()), "action": "future.secret.event"})
        self.store.roles = ["Auditor"]
        self.assertEqual(self.client.get(base.replace("alpha", "beta")).status_code, 404)
        result = self.client.get(base)
        self.assertEqual(result.status_code, 200)
        self.assertEqual({row["action"] for row in result.json()["items"]}, {"connection.created", "connection.updated"})
        self.assertEqual(len(result.json()["items"]), 2)
        self.assertNotIn("mysql.internal", result.text)
        self.assertNotIn("new.internal", result.text)
        self.assertNotIn("database_name", result.text)
        self.assertEqual(len(self.client.get(base, params={"action": "connection.created"}).json()["items"]), 1)
        self.assertEqual(self.client.get(base, params={"action": "future.secret.event"}).status_code, 400)
        self.assertEqual(self.client.get(base, params={"cursor": str(uuid4())}).status_code, 400)
        self.assertEqual(self.client.get(base, params={"cursor": self.store.audit_events[2]["id"]}).status_code, 400)
        other_actor = str(uuid4())
        self.store.audit_events.append({**self.store.audit_events[0], "id": str(uuid4()), "actor_id": other_actor})
        self.assertEqual([row["actor_id"] for row in self.client.get(base, params={"actor_id": other_actor}).json()["items"]], [other_actor])
        for offset in range(48):
            self.store.audit_events.append({**self.store.audit_events[0], "id": str(uuid4()), "created_at": START + timedelta(seconds=offset + 1)})
        first = self.client.get(base).json()
        second = self.client.get(base, params={"cursor": first["next_cursor"]}).json()
        self.assertEqual((len(first["items"]), len(second["items"])), (50, 1))
        self.assertFalse({row["id"] for row in first["items"]} & {row["id"] for row in second["items"]})
        self.store.member_of_alpha = False
        self.assertEqual(self.client.get(base).status_code, 404)

    def test_pipeline_draft_scope_references_csrf_and_audit(self):
        base = "/api/v1/projects/alpha/pipelines"
        self.assertEqual(self.client.post(base, json={}).status_code, 401)
        login = self.login()
        csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        connection_base = "/api/v1/projects/alpha/connections"
        source = self.client.post(connection_base, headers=csrf, json={"name": "Orders", "kind": "mysql_source", "host": "mysql.internal", "port": 3306, "database_name": "shop"}).json()
        target = self.client.post(connection_base, headers=csrf, json={"name": "Wide", "kind": "doris_target", "host": "doris.internal", "port": 9030, "database_name": "mart"}).json()
        fields = {"source_connection_id": source["id"], "target_connection_id": target["id"],
                  "order_table": "orders", "user_table": "users", "cycle_description": "每日人工说明，尚未排程"}
        self.assertEqual(self.client.post(base, json=fields).status_code, 403)
        self.assertEqual(self.client.post(base.replace("alpha", "beta"), json=fields, headers=csrf).status_code, 404)
        self.assertEqual(self.client.post(base, json={**fields, "password": "secret"}, headers=csrf).status_code, 400)
        self.assertEqual(self.client.post(base, json={**fields, "proposed_runtime_budget": 100}, headers=csrf).status_code, 400)
        self.assertEqual(self.client.post(base, json={**fields, "target_connection_id": source["id"]}, headers=csrf).status_code, 404)
        self.assertEqual(self.client.post(base, json={**fields, "target_connection_id": str(uuid4())}, headers=csrf).status_code, 404)
        self.store.connections[target["id"]]["project_id"] = "beta"
        self.assertEqual(self.client.post(base, json=fields, headers=csrf).status_code, 404)
        self.store.connections[target["id"]]["project_id"] = "alpha"
        self.assertEqual(len(self.store.pipelines), 0)
        created = self.client.post(base, json=fields, headers=csrf)
        self.assertEqual(created.status_code, 201)
        row = created.json()
        self.assertEqual((row["state"], row["revision"]), ("draft_unready", 1))
        self.assertIsNone(row["proposed_quality_thresholds"])
        self.assertIsNone(row["proposed_runtime_budget"])
        self.assertEqual(self.store.audit_events[-1]["request_id"], created.headers["x-request-id"])
        self.assertEqual(created.headers["location"], f"{base}/{row['id']}")
        self.assertNotIn("secret", created.text)
        url = f"{base}/{row['id']}"
        self.assertEqual(self.client.get(url).json()["cycle_description"], fields["cycle_description"])
        self.assertEqual(self.client.get(url.replace("alpha", "beta")).status_code, 404)
        self.assertEqual(self.client.patch(url, json={"cycle_description": "每周，尚未排程"}).status_code, 403)
        self.assertEqual(self.client.patch(url, json={"cycle_description": None}, headers=csrf).status_code, 400)
        self.assertEqual(self.client.patch(url, json={"target_connection_id": source["id"]}, headers=csrf).status_code, 404)
        changed = self.client.patch(url, json={"cycle_description": "每周，尚未排程"}, headers=csrf)
        self.assertEqual(changed.status_code, 200)
        self.assertEqual((changed.json()["cycle_description"], changed.json()["revision"]), ("每周，尚未排程", 2))
        self.assertEqual(self.store.audit_events[-1]["action"], "pipeline.updated")
        self.store.roles = ["Auditor"]
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.patch(url, json={"order_table": "other"}, headers=csrf).status_code, 403)
        self.assertEqual({event["action"] for event in self.client.get("/api/v1/projects/alpha/audit-events").json()["items"]}, {"connection.created"})
        self.store.member_of_alpha = False
        self.assertEqual(self.client.get(url).status_code, 404)


if __name__ == "__main__":
    unittest.main()
