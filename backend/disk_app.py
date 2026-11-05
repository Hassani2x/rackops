import json
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from server import ROOT, DATABASE, connect
from network_app import initialize_network, NetworkHandler

INCIDENT = "INC-001"


def fresh_disk():
    return {
        "filesystem_checked": False,
        "files_checked": False,
        "service_checked": False,
        "usage": 95,
        "cleaned": False,
        "verified": False,
        "output": "Inspect the filesystem, files, and database service.",
    }


def initialize_disk(path):
    initialize_network(path)
    with connect(path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS disk_lab (
                incident_id TEXT PRIMARY KEY REFERENCES incidents(id),
                state_json TEXT NOT NULL
            )
        """)
        db.execute(
            "INSERT OR IGNORE INTO disk_lab VALUES (?, ?)",
            (INCIDENT, json.dumps(fresh_disk())),
        )


def disk_snapshot(db):
    row = db.execute(
        "SELECT state_json FROM disk_lab WHERE incident_id = ?",
        (INCIDENT,),
    ).fetchone()
    state = json.loads(row["state_json"])
    state["status"] = db.execute(
        "SELECT status FROM incidents WHERE id = ?", (INCIDENT,)
    ).fetchone()["status"]
    return state


def get_disk(path):
    with connect(path) as db:
        return disk_snapshot(db)


def perform_disk_action(path, action):
    allowed = {
        "filesystem", "files", "service", "cleanup",
        "restart", "delete", "verify", "reset"
    }
    if not isinstance(action, str) or action not in allowed:
        raise ValueError("Unknown disk action")

    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        state = disk_snapshot(db)
        status = state.pop("status")

        if action == "reset":
            state = fresh_disk()
            status = "open"
            message = "Disk lab reset. Notes and history retained."

        elif state["verified"]:
            message = "Recovery already verified. Reset the disk lab to practice again."

        elif action == "filesystem":
            state["filesystem_checked"] = True
            message = (
                "SIMULATED FILESYSTEM INSPECTION\n"
                "SRV-02 root filesystem usage: {}%\n"
                "Alert threshold: 85%\n"
                "Recovery target: below 85%."
            ).format(state["usage"])

        elif action == "files":
            state["files_checked"] = True
            if state["cleaned"]:
                message = (
                    "SIMULATED FILE INSPECTION\n"
                    "Expired rotated logs: removed by approved cleanup.\n"
                    "Active logs: preserved.\n"
                    "Database files: preserved."
                )
            else:
                message = (
                    "SIMULATED FILE INSPECTION\n"
                    "Expired rotated application logs are consuming excess space.\n"
                    "The lab retention policy permits removing these expired logs.\n"
                    "Active logs and database files must be preserved."
                )

        elif action == "service":
            state["service_checked"] = True
            message = (
                "SIMULATED SERVICE INSPECTION\n"
                "Database service: running.\n"
                "Database health query: PASS.\n"
                "The disk alert requires investigation even while service is available."
            )

        elif action == "restart":
            message = (
                "NO RESTART PERFORMED\n"
                "Restarting a healthy service does not remove accumulated logs.\n"
                "Inspect disk usage and identify approved cleanup candidates."
            )

        elif action == "delete":
            message = (
                "ACTION BLOCKED\n"
                "Database files are protected application data.\n"
                "Use the approved expired-log cleanup after gathering evidence."
            )

        elif action == "cleanup":
            evidence = all(
                state[key] for key in (
                    "filesystem_checked", "files_checked", "service_checked"
                )
            )
            if not evidence:
                message = (
                    "CLEANUP BLOCKED\n"
                    "Inspect the filesystem, files, and database service first."
                )
            elif state["cleaned"]:
                message = "Approved cleanup already completed. Verify recovery."
            else:
                state["cleaned"] = True
                state["usage"] = 62
                status = "verification_required"
                message = (
                    "SIMULATED APPROVED CLEANUP\n"
                    "Removed only expired rotated application logs.\n"
                    "Active logs and database files preserved.\n"
                    "Verification is required before closing the incident."
                )

        elif action == "verify":
            if state["cleaned"] and state["usage"] < 85:
                state["verified"] = True
                status = "resolved"
                message = (
                    "SIMULATED RECOVERY VERIFIED\n"
                    "Filesystem usage: 62%, below the 85% threshold.\n"
                    "Database service: running.\n"
                    "Database health query: PASS.\n"
                    "Active logs and database files preserved.\n"
                    "Incident resolved."
                )
            else:
                message = (
                    "SIMULATED RECOVERY CHECK FAILED\n"
                    "Filesystem usage: {}%.\n"
                    "Disk usage remains above the recovery threshold.\n"
                    "Incident remains open."
                ).format(state["usage"])

        state["output"] = message
        db.execute(
            "UPDATE disk_lab SET state_json = ? WHERE incident_id = ?",
            (json.dumps(state), INCIDENT),
        )
        db.execute(
            "UPDATE incidents SET status = ? WHERE id = ?",
            (status, INCIDENT),
        )
        db.execute(
            """INSERT INTO events
               (incident_id, kind, message, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                INCIDENT,
                "disk_" + action,
                message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        result = disk_snapshot(db)
    return result


class DiskHandler(NetworkHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            return self.send(
                200,
                (ROOT / "static/disk.html").read_bytes(),
                "text/html; charset=utf-8",
            )
        if path == "/api/disk":
            return self.send(200, get_disk(DATABASE))
        return super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != "/api/disk/actions":
            return super().do_POST()

        expected = "http://127.0.0.1:{}".format(self.server.server_port)
        if self.headers.get("Origin") not in (None, expected):
            return self.send(403, {"error": "Origin not allowed"})

        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";")[0].strip() != "application/json":
            return self.send(415, {"error": "Use application/json"})

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                return self.send(413, {"error": "Request too large or empty"})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            result = perform_disk_action(DATABASE, data.get("action"))
        except (ValueError, UnicodeDecodeError) as error:
            return self.send(400, {"error": str(error)})

        self.send(200, result)


if __name__ == "__main__":
    initialize_disk(DATABASE)
    server = ThreadingHTTPServer(("127.0.0.1", 8001), DiskHandler)
    print("RackOps disk + network backend: http://127.0.0.1:8001", flush=True)
    print("Keep Terminal open. Control+C stops the server.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
