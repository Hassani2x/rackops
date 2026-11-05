import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "data" / "rackops.sqlite3"


def connect(path):
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY, role TEXT NOT NULL,
                rack TEXT NOT NULL, units TEXT NOT NULL, ip TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL REFERENCES devices(id),
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN ('open', 'verification_required', 'resolved')),
                description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL REFERENCES incidents(id),
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        db.executemany(
            "INSERT OR IGNORE INTO devices VALUES (?, ?, ?, ?, ?)",
            [
                ("SW-01", "Network Switch", "A01", "U10", "192.0.2.10"),
                ("SRV-01", "Web Server", "A01", "U08-09", "192.0.2.21"),
                ("SRV-02", "Database Server", "A01", "U06-07", "192.0.2.22"),
                ("SRV-03", "Application Server", "A01", "U04-05", "192.0.2.23"),
                ("STOR-01", "Storage Server", "A01", "U01-03", "192.0.2.24"),
            ],
        )

        incidents = [
            (
                "INC-001", "SRV-02", "High Disk Usage",
                "Disk usage alert requires investigation.",
            ),
            (
                "INC-002", "SRV-03", "Network Outage",
                "Server cannot reach its gateway or other lab servers.",
            ),
            (
                "INC-003", "SRV-01", "Power Redundancy Lost",
                "Server remains online on PSU B; PSU A reports a fault.",
            ),
        ]

        for item in incidents:
            cursor = db.execute(
                """INSERT OR IGNORE INTO incidents
                   (id, device_id, title, description)
                   VALUES (?, ?, ?, ?)""",
                item,
            )
            if cursor.rowcount:
                db.execute(
                    """INSERT INTO events
                       (incident_id, kind, message, created_at)
                       VALUES (?, 'opened', ?, ?)""",
                    (
                        item[0],
                        item[3],
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )


def make_handler(database):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, value,
                 content_type="application/json; charset=utf-8"):
            if content_type.startswith("application/json"):
                payload = json.dumps(value).encode()
            else:
                payload = value

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlsplit(self.path).path

            if path == "/":
                return self.send(
                    200,
                    (ROOT / "static/index.html").read_bytes(),
                    "text/html; charset=utf-8",
                )

            with connect(database) as db:
                if path == "/api/devices":
                    rows = db.execute("SELECT * FROM devices ORDER BY id")
                    return self.send(200, [dict(row) for row in rows])

                if path == "/api/incidents":
                    rows = db.execute("SELECT * FROM incidents ORDER BY id")
                    return self.send(200, [dict(row) for row in rows])

                parts = path.strip("/").split("/")
                if len(parts) == 3 and parts[:2] == ["api", "incidents"]:
                    incident = db.execute(
                        "SELECT * FROM incidents WHERE id = ?",
                        (parts[2],),
                    ).fetchone()

                    if incident:
                        result = dict(incident)
                        rows = db.execute(
                            """SELECT * FROM events
                               WHERE incident_id = ? ORDER BY id""",
                            (parts[2],),
                        )
                        result["events"] = [dict(row) for row in rows]
                        return self.send(200, result)

            self.send(404, {"error": "Not found"})

        def do_POST(self):
            expected_origin = "http://127.0.0.1:{}".format(
                self.server.server_port
            )
            if self.headers.get("Origin") not in (None, expected_origin):
                return self.send(403, {"error": "Origin not allowed"})

            parts = urlsplit(self.path).path.strip("/").split("/")
            if (
                len(parts) != 4
                or parts[:2] != ["api", "incidents"]
                or parts[3] != "notes"
            ):
                return self.send(404, {"error": "Not found"})

            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";")[0].strip() != "application/json":
                return self.send(415, {"error": "Use application/json"})

            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    return self.send(413, {"error": "Request too large or empty"})

                data = json.loads(self.rfile.read(size))
                note = data.get("note") if isinstance(data, dict) else None

                if (
                    not isinstance(note, str)
                    or not 1 <= len(note.strip()) <= 2000
                ):
                    return self.send(
                        400, {"error": "Enter a note of 1-2000 characters"}
                    )
            except (ValueError, UnicodeDecodeError):
                return self.send(400, {"error": "Invalid request"})

            with connect(database) as db:
                incident = db.execute(
                    "SELECT 1 FROM incidents WHERE id = ?", (parts[2],)
                ).fetchone()
                if not incident:
                    return self.send(404, {"error": "Incident not found"})

                timestamp = datetime.now(timezone.utc).isoformat()
                cursor = db.execute(
                    """INSERT INTO events
                       (incident_id, kind, message, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (parts[2], "note", note.strip(), timestamp),
                )
                result = {
                    "id": cursor.lastrowid,
                    "incident_id": parts[2],
                    "kind": "note",
                    "message": note.strip(),
                    "created_at": timestamp,
                }

            self.send(201, result)

    return Handler


if __name__ == "__main__":
    initialize(DATABASE)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 8001), make_handler(DATABASE)
    )
    print("RackOps backend: http://127.0.0.1:8001", flush=True)
    print("Keep this Terminal open. Control+C stops the server.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
