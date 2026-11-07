"""Independent simulated boot scenario. Never executes OS commands."""
import json
from datetime import datetime, timezone

from server import connect
from fiber_app import initialize_fiber

INCIDENT = "INC-005"
ACTUAL_UUID = "8f81c2ab-67d2-4e3f-9a30-3ca2bb46d051"
WRONG_UUID = "8f81c2ab-67d2-4e3f-9a30-3ca2bb46d099"


def fresh_boot():
    return dict(
        console_checked=False,
        disks_checked=False,
        fstab_checked=False,
        corrected=False,
        restarted=False,
        verified=False,
        output="Inspect the boot console, disk inventory, "
               "and filesystem configuration.",
    )


def initialize_boot(path):
    initialize_fiber(path)
    with connect(path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS boot_lab (
                incident_id TEXT PRIMARY KEY REFERENCES incidents(id),
                state_json TEXT NOT NULL
            )
        """)
        cursor = db.execute(
            """INSERT OR IGNORE INTO incidents
               (id,device_id,title,description) VALUES (?,?,?,?)""",
            (
                INCIDENT,
                "SRV-01",
                "Server Boot Failure",
                "Independent lab scenario: SRV-01 enters emergency mode "
                "after a filesystem configuration change.",
            ),
        )
        db.execute(
            "INSERT OR IGNORE INTO boot_lab VALUES (?,?)",
            (INCIDENT, json.dumps(fresh_boot())),
        )
        if cursor.rowcount:
            db.execute(
                """INSERT INTO events
                   (incident_id,kind,message,created_at)
                   VALUES (?,?,?,?)""",
                (
                    INCIDENT,
                    "opened",
                    "Boot alert opened: emergency mode; "
                    "web service unavailable.",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


def snapshot(db):
    row = db.execute(
        "SELECT state_json FROM boot_lab WHERE incident_id=?",
        (INCIDENT,),
    ).fetchone()
    state = json.loads(row["state_json"])
    state["status"] = db.execute(
        "SELECT status FROM incidents WHERE id=?", (INCIDENT,)
    ).fetchone()["status"]
    return state


def get_boot(path):
    with connect(path) as db:
        return snapshot(db)


def perform_boot_action(path, action, uuid=None):
    allowed = {
        "console", "disks", "fstab", "correct", "restart",
        "verify", "format", "reinstall", "reset",
    }
    if not isinstance(action, str) or action not in allowed:
        raise ValueError("Unknown boot action")

    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        state = snapshot(db)
        status = state.pop("status")

        if action == "reset":
            state = fresh_boot()
            status = "open"
            message = "Boot lab reset. Notes and history retained."

        elif state["verified"]:
            message = (
                "Recovery already verified. "
                "Reset the boot lab to practice again."
            )

        elif action == "console":
            state["console_checked"] = True
            if state["restarted"]:
                message = (
                    "SIMULATED BOOT CONSOLE\n"
                    "Normal multi-user startup completed.\n"
                    "Web service started."
                )
            elif state["corrected"]:
                message = (
                    "SIMULATED BOOT CONSOLE\n"
                    "Configuration corrected and validation passed.\n"
                    "Approved restart is still required."
                )
            else:
                message = (
                    "SIMULATED BOOT CONSOLE\n"
                    "You are in emergency mode.\n"
                    "Timed out waiting for UUID=" + WRONG_UUID + ".\n"
                    "Required mount /mnt/archive failed; "
                    "normal startup stopped.\n"
                    "Web service unavailable. "
                    "Root filesystem is available."
                )

        elif action == "disks":
            state["disks_checked"] = True
            message = (
                "SIMULATED DISK INVENTORY\n"
                "Root device: present; unchanged.\n"
                "Archive device: present, ext4 filesystem.\n"
                "Archive filesystem UUID: " + ACTUAL_UUID + "\n"
                "Lab disk health checks: PASS.\n"
                "No evidence supports formatting or reinstalling."
            )

        elif action == "fstab":
            state["fstab_checked"] = True
            value = ACTUAL_UUID if state["corrected"] else WRONG_UUID
            message = (
                "SIMULATED /etc/fstab INSPECTION\n"
                "Root entry: matches the plan.\n"
                "Archive entry: UUID=" + value
                + " /mnt/archive ext4 defaults 0 2\n"
                "The plan requires this archive filesystem at startup.\n"
                "Compare its UUID with the disk inventory."
            )

        elif action == "correct":
            evidence = all(
                state[key] for key in (
                    "console_checked", "disks_checked", "fstab_checked"
                )
            )
            if not evidence:
                message = (
                    "CHANGE BLOCKED\n"
                    "Inspect the console, disk inventory, "
                    "and filesystem configuration first."
                )
            elif (
                not isinstance(uuid, str)
                or uuid.strip().lower() != ACTUAL_UUID
            ):
                message = (
                    "CHANGE REJECTED\n"
                    "The supplied UUID does not match "
                    "the archive filesystem.\n"
                    "No configuration was changed."
                )
            elif state["corrected"]:
                message = (
                    "Configuration already corrected. "
                    "Complete the approved restart and verify recovery."
                )
            else:
                state["corrected"] = True
                status = "verification_required"
                message = (
                    "SIMULATED APPROVED CONFIGURATION CHANGE\n"
                    "Saved a copy of the original fstab.\n"
                    "Updated only the archive mount UUID to "
                    + ACTUAL_UUID + ".\n"
                    "Root entry and all disk contents preserved.\n"
                    "Reloaded simulated mount definitions and validated "
                    "the archive mount successfully.\n"
                    "Complete the approved restart, then verify recovery."
                )

        elif action == "restart":
            if not state["corrected"]:
                message = (
                    "RESTART DEFERRED\n"
                    "Correct and validate the faulty filesystem entry first.\n"
                    "A restart alone would repeat the same boot failure."
                )
            else:
                state["restarted"] = True
                message = (
                    "SIMULATED APPROVED RESTART COMPLETED\n"
                    "Archive mount succeeded.\n"
                    "Normal startup completed.\n"
                    "Verify the boot state and web service before resolving."
                )

        elif action in ("format", "reinstall"):
            message = (
                "ACTION BLOCKED\n"
                "Disk health evidence does not justify destructive changes.\n"
                "Preserve the data and correct the observed "
                "configuration mismatch."
            )

        elif action == "verify":
            if state["corrected"] and state["restarted"]:
                state["verified"] = True
                status = "resolved"
                message = (
                    "SIMULATED BOOT RECOVERY VERIFIED\n"
                    "Normal startup: PASS.\n"
                    "Archive mount UUID matches the disk inventory: PASS.\n"
                    "Web service running: PASS.\n"
                    "Lab HTTP health check: PASS.\n"
                    "Root entry and disk contents preserved.\n"
                    "Incident resolved."
                )
            else:
                message = (
                    "SIMULATED RECOVERY NOT VERIFIED\n"
                    + (
                        "Approved restart has not been completed."
                        if state["corrected"]
                        else "The archive mount configuration "
                        "is still incorrect."
                    )
                    + "\nIncident remains unresolved."
                )

        state["output"] = message
        db.execute(
            "UPDATE boot_lab SET state_json=? WHERE incident_id=?",
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
                INCIDENT, "boot_" + action, message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        result = snapshot(db)
    return result
