import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from accounts_app import Accounts, AccountError, make_accounts_handler
from server import connect
from network_app import get_network
from power_app import initialize_power

PASSWORD = "Local practice password 42!"


class AccountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.legacy = self.root / "rackops.sqlite3"
        initialize_power(self.legacy)
        with connect(self.legacy) as db:
            db.execute(
                """INSERT INTO events
                   (incident_id,kind,message,created_at)
                   VALUES ('INC-002','note','Original private note',
                           '2026-11-06T00:00:00Z')"""
            )
        self.accounts = Accounts(self.root / "data", self.legacy)
        page = self.root / "page.html"
        page.write_text("Login page")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_accounts_handler(self.accounts, page),
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.url = "http://127.0.0.1:{}".format(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def http(self, path, data=None, token="", extra=None):
        headers = {
            "Cookie": "rackops_session=" + token,
            "Content-Type": "application/json",
            "X-RackOps-Request": "1",
        }
        headers.update(extra or {})
        request = Request(
            self.url + path, headers=headers,
            data=json.dumps(data).encode() if data is not None else None,
        )
        try:
            with urlopen(request, timeout=10) as result:
                return result.status, result.read(), result.headers
        except HTTPError as error:
            return error.code, error.read(), error.headers

    def test_first_account_imports_progress_only_once(self):
        a, _ = self.accounts.authenticate("hassan", PASSWORD, True)
        b, _ = self.accounts.authenticate("learner2", PASSWORD, True)
        for path, expected in (
            (self.accounts.workspace(a), 1),
            (self.accounts.workspace(b), 0),
            (self.legacy, 1),
        ):
            with connect(path) as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM events WHERE kind='note'"
                ).fetchone()[0]
            self.assertEqual(count, expected)

    def test_password_storage_login_and_logout(self):
        user, token = self.accounts.authenticate("Hassan", PASSWORD, True)
        with connect(self.accounts.auth) as db:
            row = db.execute("SELECT * FROM users").fetchone()
            self.assertNotEqual(row["password_hash"], PASSWORD)
            self.assertEqual(len(row["salt"]), 32)
            self.assertNotIn(
                token, str(list(db.execute(
                    "SELECT * FROM sessions"
                ).fetchone()))
            )
        self.assertEqual(self.accounts.user(token)["username"], "hassan")
        _, second = self.accounts.authenticate("hassan", PASSWORD)
        self.accounts.logout(token)
        with self.assertRaises(AccountError):
            self.accounts.user(token)
        self.assertEqual(self.accounts.user(second)["id"], user["id"])

    def test_expired_session_and_wrong_password(self):
        _, token = self.accounts.authenticate("hassan", PASSWORD, True)
        with self.assertRaises(AccountError):
            self.accounts.authenticate("hassan", "Wrong password 123!")
        with connect(self.accounts.auth) as db:
            db.execute(
                "UPDATE sessions SET expires=?", (time.time() - 1,)
            )
        with self.assertRaises(AccountError):
            self.accounts.user(token)

    def test_api_authentication_and_cookie_flags(self):
        for path in (
            "/api/incidents", "/api/devices", "/api/network",
            "/api/disk", "/api/power", "/api/dashboard",
            "/api/incidents/INC-002/report",
        ):
            self.assertEqual(self.http(path)[0], 401)
        status, _, headers = self.http(
            "/api/auth/register",
            {"username": "hassan", "password": PASSWORD},
        )
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])

    def test_actions_notes_reports_and_dashboard_are_isolated(self):
        a, ta = self.accounts.authenticate("hassan", PASSWORD, True)
        _, tb = self.accounts.authenticate("learner2", PASSWORD, True)
        for action in ("ip", "port", "ping", "vlan", "verify"):
            self.assertEqual(self.http(
                "/api/network/actions", {"action": action}, ta
            )[0], 200)
        self.assertEqual(self.http(
            "/api/incidents/INC-002/notes",
            {"note": "Only Hassan can see this"}, ta,
        )[0], 201)
        status, report, _ = self.http(
            "/api/incidents/INC-002/report", token=ta
        )
        self.assertEqual(status, 200)
        self.assertIn(b"Only Hassan can see this", report)
        self.assertEqual(self.http(
            "/api/incidents/INC-002/report", token=tb
        )[0], 409)
        _, incident, _ = self.http(
            "/api/incidents/INC-002", token=tb
        )
        self.assertNotIn(b"Original private note", incident)
        self.assertNotIn(b"Only Hassan can see this", incident)
        self.assertEqual(json.loads(self.http(
            "/api/dashboard", token=tb
        )[1])["resolved"], 0)
        self.assertEqual(json.loads(self.http(
            "/api/dashboard", token=ta
        )[1])["resolved"], 1)
        self.assertTrue(
            get_network(self.accounts.workspace(a))["verified"]
        )

    def test_cross_site_requests_and_file_access_are_blocked(self):
        _, token = self.accounts.authenticate("hassan", PASSWORD, True)
        for extra in (
            {"Origin": "https://example.com"},
            {"X-RackOps-Request": ""},
            {"Host": "example.com"},
        ):
            self.assertEqual(self.http(
                "/api/network/actions", {"action": "reset"}, token, extra
            )[0], 403)
        for path in (
            "/data/accounts.sqlite3", "/server.py",
            "/data/workspaces/other.sqlite3",
        ):
            self.assertEqual(self.http(path, token=token)[0], 404)

    def test_data_persists_and_client_cannot_choose_workspace(self):
        a, token = self.accounts.authenticate("hassan", PASSWORD, True)
        b, tb = self.accounts.authenticate("learner2", PASSWORD, True)
        self.http("/api/network/actions", {"action": "ip"}, token)
        again = Accounts(self.accounts.directory, self.legacy)
        self.assertEqual(again.user(token)["id"], a["id"])
        self.assertTrue(get_network(again.workspace(a))["ip_checked"])
        self.http(
            "/api/network/actions",
            {"action": "port", "user_id": a["id"]}, tb,
        )
        self.assertFalse(get_network(again.workspace(a))["port_checked"])
        self.assertTrue(get_network(again.workspace(b))["port_checked"])

    def test_input_validation_and_throttling(self):
        for username, password in (
            ("../bad", PASSWORD), ("okname", "short")
        ):
            with self.assertRaises(AccountError):
                self.accounts.authenticate(username, password, True)
        with connect(self.accounts.auth) as db:
            db.executemany(
                "INSERT INTO attempts VALUES (?)",
                [(time.time(),)] * 20,
            )
        with self.assertRaises(AccountError) as caught:
            self.accounts.authenticate("hassan", PASSWORD, True)
        self.assertEqual(caught.exception.status, 429)


if __name__ == "__main__":
    unittest.main(verbosity=2)
