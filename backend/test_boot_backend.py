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
from boot_app import (
    initialize_boot, get_boot, perform_boot_action, ACTUAL_UUID
)


class BootTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "lab.sqlite3"
        initialize_boot(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def gather(self):
        for action in ("console", "disks", "fstab"):
            perform_boot_action(self.path, action)

    def test_initialization_adds_one_incident_only(self):
        initialize_boot(self.path)
        self.assertEqual(get_dashboard(self.path)["total"], 5)
        with connect(self.path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM events WHERE incident_id='INC-005'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_correction_requires_evidence_and_matching_uuid(self):
        self.assertFalse(
            perform_boot_action(
                self.path, "correct", ACTUAL_UUID
            )["corrected"]
        )
        self.gather()
        self.assertFalse(
            perform_boot_action(
                self.path, "correct", "wrong"
            )["corrected"]
        )
        self.assertEqual(get_boot(self.path)["status"], "open")
        self.assertTrue(
            perform_boot_action(
                self.path, "correct", ACTUAL_UUID
            )["corrected"]
        )

    def test_restart_and_verification_are_separate(self):
        self.gather()
        self.assertFalse(
            perform_boot_action(self.path, "restart")["restarted"]
        )
        state = perform_boot_action(
            self.path, "correct", ACTUAL_UUID
        )
        self.assertEqual(state["status"], "verification_required")
        self.assertFalse(
            perform_boot_action(self.path, "verify")["verified"]
        )
        state = perform_boot_action(self.path, "restart")
        self.assertFalse(state["verified"])
        self.assertEqual(state["status"], "verification_required")
        self.assertTrue(
            perform_boot_action(self.path, "verify")["verified"]
        )

    def test_destructive_actions_are_blocked(self):
        for action in ("format", "reinstall", "verify"):
            state = perform_boot_action(self.path, action)
            self.assertFalse(state["corrected"])
            self.assertEqual(state["status"], "open")

    def test_saved_resolution_and_report(self):
        self.gather()
        perform_boot_action(self.path, "correct", ACTUAL_UUID)
        perform_boot_action(self.path, "restart")
        perform_boot_action(self.path, "verify")
        initialize_boot(self.path)
        self.assertEqual(get_boot(self.path)["status"], "resolved")
        self.assertIn(
            "HTTP health check: PASS",
            build_report(self.path, "INC-005"),
        )

    def test_reset_preserves_notes_and_other_incidents(self):
        with connect(self.path) as db:
            db.execute(
                "UPDATE incidents SET status='resolved' WHERE id='INC-004'"
            )
            db.execute(
                """INSERT INTO events
                   (incident_id,kind,message,created_at)
                   VALUES ('INC-005','note','Keep note',
                           '2026-11-06T00:00:00Z')"""
            )
        self.gather()
        perform_boot_action(self.path, "correct", ACTUAL_UUID)
        state = perform_boot_action(self.path, "reset")
        self.assertFalse(state["corrected"])
        self.assertFalse(state["console_checked"])
        with connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT status FROM incidents WHERE id='INC-004'"
            ).fetchone()[0], "resolved")
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='note'"
            ).fetchone()[0], 1)
        with self.assertRaises(ReportError):
            build_report(self.path, "INC-005")

    def test_accounts_have_separate_boot_progress(self):
        accounts = Accounts(
            Path(self.temp.name) / "accounts", self.path
        )
        a, _ = accounts.authenticate(
            "learner1", "Example password 123!", True
        )
        b, _ = accounts.authenticate(
            "learner2", "Example password 123!", True
        )
        perform_boot_action(accounts.workspace(a), "console")
        self.assertTrue(
            get_boot(accounts.workspace(a))["console_checked"]
        )
        self.assertFalse(
            get_boot(accounts.workspace(b))["console_checked"]
        )

    def test_api_migration_and_corrective_input(self):
        accounts = Accounts(
            Path(self.temp.name) / "accounts", self.path
        )
        user, token = accounts.authenticate(
            "learner1", "Example password 123!", True
        )
        with connect(accounts.workspace(user)) as db:
            db.execute("DELETE FROM boot_lab")
            db.execute("DELETE FROM events WHERE incident_id='INC-005'")
            db.execute("DELETE FROM incidents WHERE id='INC-005'")

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
                urlopen(base + "/api/boot", timeout=5)
            self.assertEqual(caught.exception.code, 401)

            with urlopen(
                Request(base + "/api/boot", headers=headers),
                timeout=5,
            ) as response:
                self.assertEqual(json.load(response)["status"], "open")

            for action in (
                "console", "disks", "fstab",
                "correct", "restart", "verify",
            ):
                payload = json.dumps({
                    "action": action, "uuid": ACTUAL_UUID
                }).encode()
                request = Request(
                    base + "/api/boot/actions",
                    headers=headers, data=payload,
                )
                with urlopen(request, timeout=5) as response:
                    state = json.load(response)
            self.assertTrue(state["verified"])

            request = Request(
                base + "/api/incidents/INC-005/report",
                headers=headers,
            )
            with urlopen(request, timeout=5) as response:
                self.assertIn(
                    b"BOOT RECOVERY VERIFIED", response.read()
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main(verbosity=2)
