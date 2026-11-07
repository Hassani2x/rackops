import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from accounts_app import Accounts, make_accounts_handler
from server import connect
from dashboard_app import get_dashboard
from reports_app import build_report, ReportError
from fiber_app import initialize_fiber, get_fiber, perform_fiber_action


class FiberTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "lab.sqlite3"
        initialize_fiber(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def gather(self):
        for action in ("link", "optics", "connector"):
            perform_fiber_action(self.path, action)

    def test_initialization_adds_one_incident_only(self):
        initialize_fiber(self.path)
        self.assertEqual(get_dashboard(self.path)["total"], 4)
        with connect(self.path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM events WHERE incident_id='INC-004'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_cleaning_requires_all_inspections(self):
        for action in ("link", "optics"):
            perform_fiber_action(self.path, action)
        state = perform_fiber_action(self.path, "clean")
        self.assertFalse(state["cleaned"])
        self.assertIn("BLOCKED", state["output"])

    def test_cleaning_requires_reinspection_and_verification(self):
        self.gather()
        state = perform_fiber_action(self.path, "clean")
        self.assertEqual(state["status"], "verification_required")
        self.assertFalse(
            perform_fiber_action(self.path, "verify")["verified"]
        )
        state = perform_fiber_action(self.path, "reinspect")
        self.assertFalse(state["verified"])
        self.assertEqual(state["status"], "verification_required")
        self.assertTrue(
            perform_fiber_action(self.path, "verify")["verified"]
        )

    def test_wrong_actions_do_not_resolve_incident(self):
        for action in ("reinspect", "swap", "reboot", "verify"):
            self.assertEqual(
                perform_fiber_action(self.path, action)["status"], "open"
            )

    def test_saved_resolution_and_report(self):
        self.gather()
        for action in ("clean", "reinspect", "verify"):
            perform_fiber_action(self.path, action)
        initialize_fiber(self.path)
        self.assertEqual(get_fiber(self.path)["status"], "resolved")
        self.assertEqual(get_dashboard(self.path)["resolved"], 1)
        self.assertIn(
            "Lab traffic test: PASS", build_report(self.path, "INC-004")
        )

    def test_reset_keeps_notes_and_other_incidents(self):
        with connect(self.path) as db:
            db.execute(
                "UPDATE incidents SET status='resolved' WHERE id='INC-002'"
            )
            db.execute(
                """INSERT INTO events
                   (incident_id,kind,message,created_at)
                   VALUES ('INC-004','note','Keep note',
                           '2026-11-06T00:00:00Z')"""
            )
        self.gather()
        perform_fiber_action(self.path, "clean")
        state = perform_fiber_action(self.path, "reset")
        self.assertFalse(state["cleaned"])
        self.assertFalse(state["link_checked"])
        with connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT status FROM incidents WHERE id='INC-002'"
            ).fetchone()[0], "resolved")
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='note'"
            ).fetchone()[0], 1)
        with self.assertRaises(ReportError):
            build_report(self.path, "INC-004")

    def test_accounts_have_separate_fiber_progress(self):
        accounts = Accounts(
            Path(self.temp.name) / "accounts", self.path
        )
        a, _ = accounts.authenticate(
            "learner1", "Example password 123!", True
        )
        b, _ = accounts.authenticate(
            "learner2", "Example password 123!", True
        )
        first = accounts.workspace(a)
        second = accounts.workspace(b)
        perform_fiber_action(first, "link")
        self.assertTrue(get_fiber(first)["link_checked"])
        self.assertFalse(get_fiber(second)["link_checked"])

    def test_authenticated_api_and_legacy_account_migration(self):
        accounts = Accounts(
            Path(self.temp.name) / "accounts", self.path
        )
        user, token = accounts.authenticate(
            "learner1", "Example password 123!", True
        )
        with connect(accounts.workspace(user)) as db:
            db.execute("DELETE FROM fiber_lab")
            db.execute("DELETE FROM events WHERE incident_id='INC-004'")
            db.execute("DELETE FROM incidents WHERE id='INC-004'")

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_accounts_handler(accounts, Path(__file__)),
        )
        thread = threading.Thread(
            target=server.serve_forever, daemon=True
        )
        thread.start()
        base = "http://127.0.0.1:{}".format(server.server_port)
        headers = {
            "Cookie": "rackops_session=" + token,
            "Content-Type": "application/json",
            "X-RackOps-Request": "1",
        }
        try:
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + "/api/fiber", timeout=5)
            self.assertEqual(caught.exception.code, 401)

            with urlopen(
                Request(base + "/api/fiber", headers=headers),
                timeout=5,
            ) as response:
                self.assertEqual(json.load(response)["status"], "open")

            for action in (
                "link", "optics", "connector", "clean", "reinspect", "verify"
            ):
                request = Request(
                    base + "/api/fiber/actions",
                    headers=headers,
                    data=json.dumps({"action": action}).encode(),
                )
                with urlopen(request, timeout=5) as response:
                    state = json.load(response)
            self.assertTrue(state["verified"])

            request = Request(
                base + "/api/incidents/INC-004/report", headers=headers
            )
            with urlopen(request, timeout=5) as response:
                self.assertIn(
                    b"FIBER RECOVERY VERIFIED", response.read()
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main(verbosity=2)
