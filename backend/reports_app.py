import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from server import ROOT, DATABASE, connect


class ReportError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def build_report(path, incident_id):
    with connect(path) as db:
        db.execute("BEGIN")
        incident = db.execute(
            "SELECT * FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
        if incident is None:
            raise ReportError(404, "Incident not found")
        if incident["status"] != "resolved":
            raise ReportError(
                409, "Verify recovery before downloading a report"
            )

        device = db.execute(
            "SELECT * FROM devices WHERE id = ?",
            (incident["device_id"],),
        ).fetchone()
        events = db.execute(
            "SELECT * FROM events WHERE incident_id = ? ORDER BY id",
            (incident_id,),
        ).fetchall()

    lines = [
        "RACKOPS INCIDENT REPORT",
        "Simulation - no live device connections",
        "Generated (UTC): " + datetime.now(timezone.utc).isoformat(),
        "",
        "Incident: " + incident["id"],
        "Title: " + incident["title"],
        "Status: " + incident["status"],
        "Device: " + device["id"] + " - " + device["role"],
        "Location: Rack " + device["rack"] + " / " + device["units"],
        "Lab IP: " + device["ip"],
        "Description: " + incident["description"],
        "",
        "SAVED INCIDENT TIMELINE",
        "Includes inspections, attempted actions, corrections, verification, and notes.",
    ]
    for number, event in enumerate(events, 1):
        lines.extend([
            "",
            "{}. {} [{}]".format(
                number, event["created_at"], event["kind"]
            ),
            event["message"],
        ])
    lines.extend([
        "",
        "END OF REPORT",
        "This report reflects saved simulation records at download time.",
        "It is a learning record, not proof of work on live equipment.",
    ])
    return "\n".join(lines) + "\n"


def make_reports_handler(base_handler, database):
    class ReportsHandler(base_handler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                return self.send(
                    200,
                    (ROOT / "static/reports.html").read_bytes(),
                    "text/html; charset=utf-8",
                )

            parts = path.strip("/").split("/")
            if (
                len(parts) == 4
                and parts[:2] == ["api", "incidents"]
                and parts[3] == "report"
            ):
                incident_id = parts[2]
                if not re.fullmatch(r"INC-[0-9]{3}", incident_id):
                    return self.send(404, {"error": "Incident not found"})

                try:
                    payload = build_report(
                        database, incident_id
                    ).encode("utf-8")
                except ReportError as error:
                    return self.send(
                        error.status, {"error": str(error)}
                    )

                self.send_response(200)
                self.send_header(
                    "Content-Type", "text/plain; charset=utf-8"
                )
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="RackOps-{}-report.txt"'.format(
                        incident_id
                    ),
                )
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)
                return

            return super().do_GET()

    return ReportsHandler


if __name__ == "__main__":
    from http.server import ThreadingHTTPServer
    from dashboard_app import DashboardHandler
    from power_app import initialize_power

    initialize_power(DATABASE)
    handler = make_reports_handler(DashboardHandler, DATABASE)
    server = ThreadingHTTPServer(("127.0.0.1", 8001), handler)
    print("RackOps reports: http://127.0.0.1:8001", flush=True)
    print("Keep Terminal open. Control+C stops the server.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
