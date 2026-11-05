import tempfile
import unittest
from pathlib import Path

from server import connect
from network_app import get_network, perform_action
from disk_app import get_disk, perform_disk_action
from power_app import initialize_power, get_power, perform_power_action


class PowerBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        initialize_power(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def gather(self):
        for action in ("psu", "feeds", "events"):
            perform_power_action(self.path, action)

    def test_initial_incident(self):
        state = get_power(self.path)
        self.assertEqual(state["status"], "open")
        self.assertFalse(state["replaced"])
        self.assertFalse(state["verified"])

    def test_replacement_requires_all_evidence(self):
        perform_power_action(self.path, "psu")
        perform_power_action(self.path, "feeds")
        state = perform_power_action(self.path, "replace")
        self.assertFalse(state["replaced"])
        self.assertEqual(state["status"], "open")
        self.assertIn("BLOCKED", state["output"])

    def test_working_power_path_is_preserved(self):
        for action in ("disconnect", "reboot"):
            state = perform_power_action(self.path, action)
            self.assertFalse(state["replaced"])
            self.assertFalse(state["verified"])
            self.assertEqual(state["status"], "open")
        self.assertIn("NO REBOOT", state["output"])

    def test_verification_fails_before_replacement(self):
        self.gather()
        state = perform_power_action(self.path, "verify")
        self.assertFalse(state["verified"])
        self.assertEqual(state["status"], "open")
        self.assertIn("FAILED", state["output"])

    def test_replacement_requires_verification(self):
        self.gather()
        state = perform_power_action(self.path, "replace")
        self.assertTrue(state["replaced"])
        self.assertFalse(state["verified"])
        self.assertEqual(state["status"], "verification_required")

    def test_verified_recovery_persists(self):
        self.gather()
        perform_power_action(self.path, "replace")
        perform_power_action(self.path, "verify")
        initialize_power(self.path)
        state = get_power(self.path)
        self.assertTrue(state["verified"])
        self.assertEqual(state["status"], "resolved")

    def test_reset_keeps_notes_and_other_progress(self):
        for action in ("ip", "port", "ping", "vlan", "verify"):
            perform_action(self.path, action)
        for action in ("filesystem", "files", "service", "cleanup", "verify"):
            perform_disk_action(self.path, action)

        network_before = get_network(self.path)
        disk_before = get_disk(self.path)

        with connect(self.path) as db:
            db.execute(
                """INSERT INTO events
                   (incident_id, kind, message, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("INC-003", "note", "Preserve PSU B", "2026-11-05T12:00:00Z"),
            )

        self.gather()
        perform_power_action(self.path, "replace")
        perform_power_action(self.path, "verify")
        state = perform_power_action(self.path, "reset")

        self.assertEqual(state["status"], "open")
        self.assertFalse(state["replaced"])
        self.assertFalse(state["psu_checked"])
        self.assertEqual(get_network(self.path), network_before)
        self.assertEqual(get_disk(self.path), disk_before)

        with connect(self.path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM events WHERE kind = 'note'"
            ).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
