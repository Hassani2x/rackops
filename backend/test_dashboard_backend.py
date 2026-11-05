import tempfile
import unittest
from pathlib import Path

from server import connect
from network_app import perform_action
from disk_app import perform_disk_action
from power_app import initialize_power, perform_power_action
from dashboard_app import get_dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        initialize_power(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def prepare_network(self):
        for action in ("ip", "port", "ping", "vlan"):
            perform_action(self.path, action)

    def test_fresh_counts(self):
        self.assertEqual(
            get_dashboard(self.path),
            {"total": 3, "open": 3, "awaiting": 0, "resolved": 0, "devices": 5},
        )

    def test_correction_moves_to_awaiting(self):
        self.prepare_network()
        counts = get_dashboard(self.path)
        self.assertEqual(counts["open"], 2)
        self.assertEqual(counts["awaiting"], 1)
        self.assertEqual(counts["resolved"], 0)

    def test_failed_verification_does_not_resolve(self):
        perform_action(self.path, "verify")
        counts = get_dashboard(self.path)
        self.assertEqual(counts["open"], 3)
        self.assertEqual(counts["resolved"], 0)

    def test_all_three_can_resolve(self):
        self.prepare_network()
        perform_action(self.path, "verify")
        for action in ("filesystem", "files", "service", "cleanup", "verify"):
            perform_disk_action(self.path, action)
        for action in ("psu", "feeds", "events", "replace", "verify"):
            perform_power_action(self.path, action)
        counts = get_dashboard(self.path)
        self.assertEqual(counts["open"], 0)
        self.assertEqual(counts["awaiting"], 0)
        self.assertEqual(counts["resolved"], 3)

    def test_reset_reopens_only_one_incident(self):
        self.prepare_network()
        perform_action(self.path, "verify")
        for action in ("psu", "feeds", "events", "replace", "verify"):
            perform_power_action(self.path, action)
        perform_power_action(self.path, "reset")
        counts = get_dashboard(self.path)
        self.assertEqual(counts["open"], 2)
        self.assertEqual(counts["resolved"], 1)

    def test_counts_persist_without_changing_timeline(self):
        self.prepare_network()
        with connect(self.path) as db:
            before = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        expected = get_dashboard(self.path)
        initialize_power(self.path)
        self.assertEqual(get_dashboard(self.path), expected)
        with connect(self.path) as db:
            after = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
