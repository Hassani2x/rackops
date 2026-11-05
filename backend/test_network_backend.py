import tempfile
import unittest
from pathlib import Path

from server import connect
from network_app import initialize_network, get_network, perform_action


class NetworkBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        initialize_network(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def gather(self):
        for action in ("ip", "port", "ping"):
            perform_action(self.path, action)

    def test_initial_incident(self):
        state = get_network(self.path)
        self.assertEqual(state["vlan"], 30)
        self.assertEqual(state["status"], "open")
        self.assertFalse(state["verified"])

    def test_change_requires_all_evidence(self):
        perform_action(self.path, "ip")
        perform_action(self.path, "port")
        state = perform_action(self.path, "vlan")
        self.assertEqual(state["vlan"], 30)
        self.assertIn("BLOCKED", state["output"])
        self.assertEqual(state["status"], "open")

    def test_verification_fails_before_correction(self):
        self.gather()
        state = perform_action(self.path, "verify")
        self.assertFalse(state["verified"])
        self.assertEqual(state["status"], "open")

    def test_correction_requires_verification(self):
        self.gather()
        state = perform_action(self.path, "vlan")
        self.assertEqual(state["vlan"], 20)
        self.assertEqual(state["status"], "verification_required")
        self.assertFalse(state["verified"])

    def test_verified_recovery_survives_initialization(self):
        self.gather()
        perform_action(self.path, "vlan")
        perform_action(self.path, "verify")
        initialize_network(self.path)
        state = get_network(self.path)
        self.assertTrue(state["verified"])
        self.assertEqual(state["status"], "resolved")

    def test_reset_keeps_notes_and_other_incidents(self):
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO events
                   (incident_id, kind, message, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("INC-002", "note", "Keep this note", "2026-11-05T12:00:00Z"),
            )
        self.gather()
        perform_action(self.path, "vlan")
        perform_action(self.path, "verify")
        state = perform_action(self.path, "reset")
        self.assertEqual(state["vlan"], 30)
        self.assertEqual(state["status"], "open")
        self.assertFalse(state["ip_checked"])
        with connect(self.path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM events WHERE kind = 'note'"
            ).fetchone()[0]
            other = db.execute(
                "SELECT status FROM incidents WHERE id = 'INC-003'"
            ).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(other, "open")


if __name__ == "__main__":
    unittest.main(verbosity=2)
