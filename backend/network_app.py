import json
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from server import ROOT, DATABASE, connect, initialize, make_handler

INCIDENT = "INC-002"


def fresh_state():
    return {
        "ip_checked": False,
        "port_checked": False,
        "ping_checked": False,
        "vlan": 30,
        "verified": False,
        "output": "Choose an inspection to gather evidence.",
    }


def initialize_network(path):
    initialize(path)
    with connect(path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS network_lab (
                incident_id TEXT PRIMARY KEY REFERENCES incidents(id),
                state_json TEXT NOT NULL
            )
        """)
        db.execute(
            "INSERT OR IGNORE INTO network_lab VALUES (?, ?)",
            (INCIDENT, json.dumps(fresh_state())),
        )


def read_state(db):
    row = db.execute(
        "SELECT state_json FROM network_lab WHERE incident_id = ?",
        (INCIDENT,),
    ).fetchone()
    return json.loads(row["state_json"])


def snapshot(db):
    state = read_state(db)
    state["status"] = db.execute(
        "SELECT status FROM incidents WHERE id = ?", (INCIDENT,)
    ).fetchone()["status"]
    return state


def get_network(path):
    with connect(path) as db:
        return snapshot(db)


def perform_action(path, action):
    allowed = {"ip", "port", "ping", "vlan", "renew", "enable", "verify", "reset"}
    if not isinstance(action, str) or action not in allowed:
        raise ValueError("Unknown network action")

    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        state = read_state(db)
        status = db.execute(
            "SELECT status FROM incidents WHERE id = ?", (INCIDENT,)
        ).fetchone()["status"]

        if action == "reset":
            state = fresh_state()
            status = "open"
            message = "Network lab reset. Inspection evidence cleared; history retained."

        elif state["verified"]:
            message = "Recovery already verified. Reset the network lab to practice again."

        elif action == "ip":
            state["ip_checked"] = True
            message = (
                "SIMULATED IP CONFIGURATION\n"
                "SRV-03: 192.0.2.23/24\n"
                "Gateway: 192.0.2.1\n"
                "Both settings match the expected plan."
            )

        elif action == "port":
            state["port_checked"] = True
            message = (
                "SIMULATED SWITCH PORT\n"
                "SW-01 Gi0/3: link UP\n"
                "Mode: access\n"
                "Current access VLAN: {}\n"
                "Expected access VLAN: 20"
            ).format(state["vlan"])

        elif action == "ping":
            state["ping_checked"] = True
            result = "PASS" if state["vlan"] == 20 else "FAIL"
            message = (
                "SIMULATED CONNECTIVITY TEST\n"
                "Gateway 192.0.2.1: {}\n"
                "Web server 192.0.2.21: {}\n"
                "A connectivity test alone does not close the incident."
            ).format(result, result)

        elif action == "renew":
            message = (
                "NO CHANGE APPLIED\n"
                "The planned static IP configuration is already correct. "
                "Renewing it would not correct a switch VLAN mismatch."
            )

        elif action == "enable":
            message = (
                "NO CHANGE APPLIED\n"
                "Gi0/3 is already UP. Inspect its VLAN configuration."
            )

        elif action == "vlan":
            evidence = all(
                state[key]
                for key in ("ip_checked", "port_checked", "ping_checked")
            )
            if not evidence:
                message = (
                    "CHANGE BLOCKED\n"
                    "Inspect IP configuration, inspect the switch port, "
                    "and test connectivity before changing the VLAN."
                )
            elif state["vlan"] == 20:
                message = "VLAN is already 20. Verify network recovery."
            else:
                state["vlan"] = 20
                status = "verification_required"
                message = (
                    "SIMULATED APPROVED CHANGE\n"
                    "SW-01 Gi0/3 access VLAN changed from 30 to 20.\n"
                    "IP configuration remains unchanged.\n"
                    "Recovery verification is still required."
                )

        elif action == "verify":
            if state["vlan"] == 20:
                state["verified"] = True
                status = "resolved"
                message = (
                    "SIMULATED RECOVERY VERIFIED\n"
                    "Gateway 192.0.2.1: PASS\n"
                    "Web server 192.0.2.21: PASS\n"
                    "Access VLAN: 20, matches plan.\n"
                    "Incident resolved."
                )
            else:
                message = (
                    "SIMULATED RECOVERY CHECK FAILED\n"
                    "Gateway 192.0.2.1: FAIL\n"
                    "Web server 192.0.2.21: FAIL\n"
                    "Incident remains open."
                )

        state["output"] = message
        db.execute(
            "UPDATE network_lab SET state_json = ? WHERE incident_id = ?",
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
                "network_" + action,
                message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        result = snapshot(db)
    return result


BaseHandler = make_handler(DATABASE)


class NetworkHandler(BaseHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            return self.send(
                200,
                (ROOT / "static/network.html").read_bytes(),
                "text/html; charset=utf-8",
            )
        if path == "/api/network":
            return self.send(200, get_network(DATABASE))
        return super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != "/api/network/actions":
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
            result = perform_action(DATABASE, data.get("action"))
        except (ValueError, UnicodeDecodeError) as error:
            return self.send(400, {"error": str(error)})

        self.send(200, result)


if __name__ == "__main__":
    initialize_network(DATABASE)
    server = ThreadingHTTPServer(("127.0.0.1", 8001), NetworkHandler)
    print("RackOps network backend: http://127.0.0.1:8001", flush=True)
    print("Keep Terminal open. Control+C stops the server.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
