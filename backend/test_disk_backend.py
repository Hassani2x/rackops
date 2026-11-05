import tempfile
import unittest
from pathlib import Path

from server import connect
from network_app import get_network
from disk_app import initialize_disk, get_disk, perform_disk_action


class DiskBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        initialize_disk(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def gather(self):
        for action in ("filesystem", "files", "service"):
            perform_disk_action(self.path, action)

    def test_cleanup_requires_all_evidence(self):
        perform_disk_action(self.path, "filesystem")
        perform_disk_action(self.path, "files")
        state = perform_disk_action(self.path, "cleanup")
        self.assertEqual(state["usage"], 95)
        self.assertFalse(state["cleaned"])
        self.assertIn("BLOCKED", state["output"])

    def test_wrong_actions_preserve_state(self):
        for action in ("restart", "delete"):
            state = perform_disk_action(self.path, action)
            self.assertEqual(state["usage"], 95)
            self.assertFalse(state["cleaned"])
            self.assertEqual(state["status"], "open")

    def test_verification_fails_before_cleanup(self):
        self.gather()
        state = perform_disk_action(self.path, "verify")
        self.assertFalse(state["verified"])
        self.assertEqual(state["status"], "open")

    def test_cleanup_requires_verification(self):
        self.gather()
        state = perform_disk_action(self.path, "cleanup")
        self.assertEqual(state["usage"], 62)
        self.assertEqual(state["status"], "verification_required")
        self.assertFalse(state["verified"])

    def test_resolution_survives_initialization(self):
        self.gather()
        perform_disk_action(self.path, "cleanup")
        perform_disk_action(self.path, "verify")
        initialize_disk(self.path)
        state = get_disk(self.path)
        self.assertTrue(state["verified"])
        self.assertEqual(state["status"], "resolved")

    def test_reset_preserves_notes_and_network(self):
        before = get_network(self.path)
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO events
                   (incident_id, kind, message, created_at)
                   VALUES (?, ?, ?, ?)""",
                ("INC-001", "note", "Keep this note", "2026-11-05T12:00:00Z"),
            )
        self.gather()
        perform_disk_action(self.path, "cleanup")
        perform_disk_action(self.path, "verify")
        state = perform_disk_action(self.path, "reset")
        self.assertEqual(state["usage"], 95)
        self.assertEqual(state["status"], "open")
        self.assertFalse(state["filesystem_checked"])
        self.assertEqual(get_network(self.path), before)
        with connect(self.path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM events WHERE kind = 'note'"
            ).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
