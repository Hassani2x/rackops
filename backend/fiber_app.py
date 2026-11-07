"""Simulated fiber incident; optical values are scenario-specific."""
import json
from datetime import datetime, timezone

from server import connect
from power_app import initialize_power

INCIDENT = "INC-004"


def fresh_fiber():
    return dict(
        link_checked=False,
        optics_checked=False,
        connector_checked=False,
        cleaned=False,
        reinspected=False,
        verified=False,
        output="Inspect the link, optical diagnostics, and connector.",
    )


def initialize_fiber(path):
    initialize_power(path)
    with connect(path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS fiber_lab (
                incident_id TEXT PRIMARY KEY REFERENCES incidents(id),
                state_json TEXT NOT NULL
            )
        """)
        cursor = db.execute(
            """INSERT OR IGNORE INTO incidents
               (id,device_id,title,description) VALUES (?,?,?,?)""",
            (
                INCIDENT,
                "STOR-01",
                "Fiber Connectivity Loss",
                "STOR-01 fiber uplink to SW-01 is down. "
                "Investigate before changing components.",
            ),
        )
        db.execute(
            "INSERT OR IGNORE INTO fiber_lab VALUES (?,?)",
            (INCIDENT, json.dumps(fresh_fiber())),
        )
        if cursor.rowcount:
            db.execute(
                """INSERT INTO events
                   (incident_id,kind,message,created_at)
                   VALUES (?,?,?,?)""",
                (
                    INCIDENT,
                    "opened",
                    "Fiber uplink alert opened for STOR-01.",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


def snapshot(db):
    row = db.execute(
        "SELECT state_json FROM fiber_lab WHERE incident_id=?",
        (INCIDENT,),
    ).fetchone()
    state = json.loads(row["state_json"])
    state["status"] = db.execute(
        "SELECT status FROM incidents WHERE id=?", (INCIDENT,)
    ).fetchone()["status"]
    return state


def get_fiber(path):
    with connect(path) as db:
        return snapshot(db)


def perform_fiber_action(path, action):
    allowed = {
        "link", "optics", "connector", "clean", "reinspect",
        "swap", "reboot", "verify", "reset",
    }
    if not isinstance(action, str) or action not in allowed:
        raise ValueError("Unknown fiber action")

    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        state = snapshot(db)
        status = state.pop("status")
        ready = state["cleaned"] and state["reinspected"]

        if action == "reset":
            state = fresh_fiber()
            status = "open"
            message = "Fiber lab reset. Notes and history retained."

        elif state["verified"]:
            message = (
                "Recovery already verified. "
                "Reset the fiber lab to practice again."
            )

        elif action == "link":
            state["link_checked"] = True
            message = (
                "SIMULATED LINK INSPECTION\n"
                "STOR-01 uplink to SW-01.\n"
                "Both interfaces administratively enabled.\n"
                "Operational link: " + ("UP." if ready else "DOWN.")
            )

        elif action == "optics":
            state["optics_checked"] = True
            message = (
                "SIMULATED OPTICAL DIAGNOSTICS\n"
                "Matching optics and fiber type for this lab.\n"
                "Transmit diagnostics at both ends: normal.\n"
                "Lab receive-power range: -12 to -1 dBm.\n"
                "STOR-01 received power: "
                + (
                    "-4 dBm, within range."
                    if ready else "-16 dBm, below range."
                )
                + "\nThese are scenario values, "
                "not universal transceiver specifications."
            )

        elif action == "connector":
            state["connector_checked"] = True
            message = (
                "SIMULATED CONNECTOR INSPECTION\n"
                "Approved optical-source isolation completed for inspection.\n"
                "Video inspection: "
                + (
                    "cleaning completed; post-clean reinspection "
                    "is still required."
                    if state["cleaned"]
                    else "contamination at the patch-cord connector endface.\n"
                    "No physical damage observed."
                )
                + "\nNo live fiber was accessed."
            )

        elif action == "clean":
            evidence = all(
                state[key] for key in (
                    "link_checked", "optics_checked", "connector_checked"
                )
            )
            if not evidence:
                message = (
                    "CLEANING BLOCKED\n"
                    "Inspect link status, optical diagnostics, "
                    "and connector condition first."
                )
            elif state["cleaned"]:
                message = (
                    "Cleaning already completed. "
                    "Reinspect the connector, then verify recovery."
                )
            else:
                state["cleaned"] = True
                status = "verification_required"
                message = (
                    "SIMULATED APPROVED CLEANING\n"
                    "Source isolated using the approved lab procedure.\n"
                    "Cleaned the contaminated patch-cord connector "
                    "with the approved connector tool.\n"
                    "Reinspection is required before reconnection "
                    "and verification."
                )

        elif action == "reinspect":
            if not state["cleaned"]:
                message = (
                    "REINSPECTION NOT PASSED\n"
                    "Contamination remains. Gather evidence "
                    "and apply approved cleaning."
                )
            else:
                state["reinspected"] = True
                message = (
                    "SIMULATED REINSPECTION PASSED\n"
                    "Patch-cord connector and mating interface: "
                    "clean; no damage.\n"
                    "Approved reconnection and optical-source "
                    "restoration completed.\n"
                    "Verify optical readings, link state, and traffic "
                    "before resolving."
                )

        elif action in ("swap", "reboot"):
            message = (
                "NO CHANGE APPLIED\n"
                + ("Optic replacement" if action == "swap" else "Server reboot")
                + " is not justified by the current evidence.\n"
                "Inspect the fiber path and correct "
                "the observed contamination."
            )

        elif action == "verify":
            if ready:
                state["verified"] = True
                status = "resolved"
                message = (
                    "SIMULATED FIBER RECOVERY VERIFIED\n"
                    "Connector reinspection: PASS.\n"
                    "STOR-01 receive power: -4 dBm, "
                    "within the lab range.\n"
                    "Operational link: UP.\n"
                    "Lab traffic test: PASS.\n"
                    "Incident resolved."
                )
            else:
                message = (
                    "SIMULATED RECOVERY NOT VERIFIED\n"
                    + (
                        "Post-clean connector reinspection "
                        "is still required."
                        if state["cleaned"]
                        else "Link remains down; receive power "
                        "is below the lab range."
                    )
                    + "\nIncident remains unresolved."
                )

        state["output"] = message
        db.execute(
            "UPDATE fiber_lab SET state_json=? WHERE incident_id=?",
            (json.dumps(state), INCIDENT),
        )
        db.execute(
            "UPDATE incidents SET status=? WHERE id=?",
            (status, INCIDENT),
        )
        db.execute(
            """INSERT INTO events
               (incident_id,kind,message,created_at)
               VALUES (?,?,?,?)""",
            (
                INCIDENT, "fiber_" + action, message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        result = snapshot(db)
    return result
