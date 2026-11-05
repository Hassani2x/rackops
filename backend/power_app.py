import json
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from server import ROOT, DATABASE, connect
from disk_app import initialize_disk, DiskHandler

INCIDENT = "INC-003"


def fresh_power():
    return {
        "psu_checked": False,
        "feeds_checked": False,
        "events_checked": False,
        "replaced": False,
        "verified": False,
        "output": "Inspect the power supplies, independent feeds, and event log.",
    }


def initialize_power(path):
    initialize_disk(path)
    with connect(path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS power_lab (
                incident_id TEXT PRIMARY KEY REFERENCES incidents(id),
                state_json TEXT NOT NULL
            )
        """)
        db.execute(
            "INSERT OR IGNORE INTO power_lab VALUES (?, ?)",
            (INCIDENT, json.dumps(fresh_power())),
        )


def power_snapshot(db):
    row = db.execute(
        "SELECT state_json FROM power_lab WHERE incident_id = ?",
        (INCIDENT,),
    ).fetchone()
    state = json.loads(row["state_json"])
    state["status"] = db.execute(
        "SELECT status FROM incidents WHERE id = ?", (INCIDENT,)
    ).fetchone()["status"]
    return state


def get_power(path):
    with connect(path) as db:
        return power_snapshot(db)


def perform_power_action(path, action):
    allowed = {
        "psu", "feeds", "events", "replace",
        "disconnect", "reboot", "verify", "reset"
    }
    if not isinstance(action, str) or action not in allowed:
        raise ValueError("Unknown power action")

    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        state = power_snapshot(db)
        status = state.pop("status")

        if action == "reset":
            state = fresh_power()
            status = "open"
            message = "Power lab reset. Notes and history retained."

        elif state["verified"]:
            message = "Recovery already verified. Reset the power lab to practice again."

        elif action == "psu":
            state["psu_checked"] = True
            if state["replaced"]:
                message = (
                    "SIMULATED PSU INSPECTION\n"
                    "PSU A: healthy; DC output available.\n"
                    "PSU B: healthy; DC output available.\n"
                    "Server: online.\n"
                    "Verify redundancy before closing the incident."
                )
            else:
                message = (
                    "SIMULATED PSU INSPECTION\n"
                    "PSU A: internal fault; no DC output.\n"
                    "PSU B: healthy; currently powering the server.\n"
                    "Server: online, but power redundancy is lost.\n"
                    "Preserve PSU B and its working feed."
                )

        elif action == "feeds":
            state["feeds_checked"] = True
            message = (
                "SIMULATED POWER FEED INSPECTION\n"
                "Feed A: available; PSU A cable seated.\n"
                "Feed B: available; PSU B cable seated.\n"
                "The lab models two independent power feeds.\n"
                "No upstream feed failure is indicated."
            )

        elif action == "events":
            state["events_checked"] = True
            message = (
                "SIMULATED EVENT LOG\n"
                "PSU A reported an internal hardware fault.\n"
                "PSU B continued supplying power.\n"
                "No upstream feed-loss event was recorded."
            )
            if state["replaced"]:
                message += "\nLater event: approved PSU A replacement completed."

        elif action == "disconnect":
            message = (
                "ACTION BLOCKED\n"
                "PSU B is the working power path that must be preserved.\n"
                "Disconnecting it while PSU A has failed could shut down the server.\n"
                "No power feed was disconnected."
            )

        elif action == "reboot":
            message = (
                "NO REBOOT PERFORMED\n"
                "A reboot does not repair a confirmed internal PSU fault.\n"
                "Preserve service and investigate the failed power supply."
            )

        elif action == "replace":
            evidence = all(
                state[key]
                for key in ("psu_checked", "feeds_checked", "events_checked")
            )
            if not evidence:
                message = (
                    "REPLACEMENT BLOCKED\n"
                    "Inspect the PSUs, power feeds, and event log first."
                )
            elif state["replaced"]:
                message = "PSU A replacement already completed. Verify power recovery."
            else:
                state["replaced"] = True
                status = "verification_required"
                message = (
                    "SIMULATED APPROVED REPLACEMENT\n"
                    "Replaced only the failed PSU A.\n"
                    "PSU B and its feed remained connected.\n"
                    "Server remained online throughout the simulated change.\n"
                    "Verify both PSUs and redundancy before resolving."
                )

        elif action == "verify":
            if state["replaced"]:
                state["verified"] = True
                status = "resolved"
                message = (
                    "SIMULATED POWER RECOVERY VERIFIED\n"
                    "PSU A health and DC output: PASS.\n"
                    "PSU B health and DC output: PASS.\n"
                    "Independent power feeds: available.\n"
                    "Power redundancy: restored.\n"
                    "Server remained online.\n"
                    "Incident resolved."
                )
            else:
                message = (
                    "SIMULATED RECOVERY CHECK FAILED\n"
                    "PSU A: internal fault remains.\n"
                    "PSU B: healthy; server remains online.\n"
                    "Power redundancy is not restored.\n"
                    "Incident remains open."
                )

        state["output"] = message
        db.execute(
            "UPDATE power_lab SET state_json = ? WHERE incident_id = ?",
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
                "power_" + action,
                message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        result = power_snapshot(db)
    return result


class PowerHandler(DiskHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            return self.send(
                200,
                (ROOT / "static/power.html").read_bytes(),
                "text/html; charset=utf-8",
            )
        if path == "/api/power":
            return self.send(200, get_power(DATABASE))
        return super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != "/api/power/actions":
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
            result = perform_power_action(DATABASE, data.get("action"))
        except (ValueError, UnicodeDecodeError) as error:
            return self.send(400, {"error": str(error)})

        self.send(200, result)


if __name__ == "__main__":
    initialize_power(DATABASE)
    server = ThreadingHTTPServer(("127.0.0.1", 8001), PowerHandler)
    print("RackOps three-incident backend: http://127.0.0.1:8001", flush=True)
    print("Keep Terminal open. Control+C stops the server.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
