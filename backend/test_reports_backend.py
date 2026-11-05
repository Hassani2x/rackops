import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from server import connect, initialize, make_handler
from reports_app import ReportError, build_report, make_reports_handler


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        initialize(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def resolve(self, incident="INC-002"):
        with connect(self.path) as db:
            db.execute(
                "UPDATE incidents SET status='resolved' WHERE id=?",
                (incident,),
            )
            db.execute(
                """INSERT INTO events
                   (incident_id,kind,message,created_at)
                   VALUES(?,?,?,?)""",
                (
                    incident, "verification", "Recovery verified",
                    "2026-11-05T12:00:00Z",
                ),
            )

    def test_open_incident_cannot_download(self):
        with self.assertRaises(ReportError) as caught:
            build_report(self.path, "INC-002")
        self.assertEqual(caught.exception.status, 409)

    def test_awaiting_verification_cannot_download(self):
        with connect(self.path) as db:
            db.execute(
                """UPDATE incidents
                   SET status='verification_required'
                   WHERE id='INC-002'"""
            )
        with self.assertRaises(ReportError) as caught:
            build_report(self.path, "INC-002")
        self.assertEqual(caught.exception.status, 409)

    def test_missing_incident(self):
        with self.assertRaises(ReportError) as caught:
            build_report(self.path, "INC-999")
        self.assertEqual(caught.exception.status, 404)

    def test_saved_notes_and_timeline_order(self):
        self.resolve()
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO events
                   (incident_id,kind,message,created_at)
                   VALUES(?,?,?,?)""",
                (
                    "INC-002", "note",
                    "Compared VLAN 30 with expected VLAN 20.",
                    "2026-11-05T12:01:00Z",
                ),
            )
        report = build_report(self.path, "INC-002")
        self.assertIn("SRV-03", report)
        self.assertIn("Status: resolved", report)
        self.assertIn("Compared VLAN 30", report)
        self.assertLess(
            report.index("Recovery verified"),
            report.index("Compared VLAN 30"),
        )
        self.assertIn(
            "Simulation - no live device connections", report
        )

    def test_other_incident_notes_not_included(self):
        self.resolve()
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO events
                   (incident_id,kind,message,created_at)
                   VALUES(?,?,?,?)""",
                (
                    "INC-003", "note", "Unrelated power note",
                    "2026-11-05T12:00:00Z",
                ),
            )
        self.assertNotIn(
            "Unrelated power note",
            build_report(self.path, "INC-002"),
        )

    def test_download_does_not_change_saved_records(self):
        self.resolve()
        with connect(self.path) as db:
            before = [
                tuple(row)
                for row in db.execute("SELECT * FROM events ORDER BY id")
            ]
        build_report(self.path, "INC-002")
        build_report(self.path, "INC-002")
        with connect(self.path) as db:
            after = [
                tuple(row)
                for row in db.execute("SELECT * FROM events ORDER BY id")
            ]
        self.assertEqual(before, after)

    def test_http_attachment_and_open_incident_error(self):
        self.resolve()
        handler = make_reports_handler(
            make_handler(self.path), self.path
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(
            target=server.serve_forever, daemon=True
        )
        thread.start()
        base = "http://127.0.0.1:{}".format(server.server_port)
        try:
            with urlopen(
                base + "/api/incidents/INC-002/report", timeout=5
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(
                    "text/plain", response.headers["Content-Type"]
                )
                self.assertIn(
                    "RackOps-INC-002-report.txt",
                    response.headers["Content-Disposition"],
                )
                self.assertIn(
                    "Recovery verified", response.read().decode()
                )
            with self.assertRaises(HTTPError) as caught:
                urlopen(
                    base + "/api/incidents/INC-001/report", timeout=5
                )
            self.assertEqual(caught.exception.code, 409)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main(verbosity=2)
