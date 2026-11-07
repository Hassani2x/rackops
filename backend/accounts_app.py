import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from server import connect
from network_app import get_network, perform_action
from disk_app import get_disk, perform_disk_action
from power_app import get_power, perform_power_action
from fiber_app import initialize_fiber, get_fiber, perform_fiber_action
from dashboard_app import get_dashboard
from reports_app import build_report, ReportError

ROUNDS = 600000
TTL = 8 * 60 * 60


class AccountError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class Accounts:
    def __init__(self, directory, legacy):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "workspaces").mkdir(exist_ok=True)
        self.auth = self.directory / "accounts.sqlite3"
        self.legacy = Path(legacy)
        with connect(self.auth) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    created REAL NOT NULL
                );
            """)

    def workspace(self, user):
        return self.directory / "workspaces" / (user["id"] + ".sqlite3")

    def authenticate(self, username, password, register=False):
        if not isinstance(username, str) or not isinstance(password, str):
            raise AccountError(400, "Enter a username and password")
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,32}", username):
            raise AccountError(
                400, "Username: 3-32 letters, numbers, or underscores"
            )
        if not 12 <= len(password) <= 128:
            raise AccountError(400, "Password: 12-128 characters")

        with connect(self.auth) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM attempts WHERE created < ?",
                (time.time() - 300,),
            )
            count = db.execute(
                "SELECT COUNT(*) FROM attempts"
            ).fetchone()[0]
            if count >= 20:
                raise AccountError(
                    429, "Too many attempts. Wait five minutes."
                )
            db.execute("INSERT INTO attempts VALUES (?)", (time.time(),))

        with connect(self.auth) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM users WHERE username=?", (username,)
            ).fetchone()
            salt = (
                secrets.token_hex(16)
                if register or row is None
                else row["salt"]
            )
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt), ROUNDS
            ).hex()

            if register:
                if row is not None:
                    raise AccountError(409, "Username already exists")
                first = db.execute(
                    "SELECT COUNT(*) FROM users"
                ).fetchone()[0] == 0
                user = {
                    "id": secrets.token_hex(16),
                    "username": username,
                }
                target = self.workspace(user)
                try:
                    if first and self.legacy.is_file():
                        with sqlite3.connect(str(self.legacy)) as original:
                            with sqlite3.connect(str(target)) as copy:
                                original.backup(copy)
                    initialize_fiber(target)
                    db.execute(
                        "INSERT INTO users VALUES (?,?,?,?)",
                        (user["id"], username, salt, digest),
                    )
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
            else:
                if row is None or not hmac.compare_digest(
                    digest, row["password_hash"]
                ):
                    raise AccountError(
                        401, "Incorrect username or password"
                    )
                user = {
                    "id": row["id"],
                    "username": row["username"],
                }

            token = secrets.token_urlsafe(32)
            db.execute(
                "DELETE FROM sessions WHERE expires <= ?",
                (time.time(),),
            )
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    user["id"],
                    time.time() + TTL,
                ),
            )
        return user, token

    def user(self, token):
        with connect(self.auth) as db:
            row = db.execute(
                """SELECT u.id,u.username FROM users u
                   JOIN sessions s ON s.user_id=u.id
                   WHERE s.token_hash=? AND s.expires>?""",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    time.time(),
                ),
            ).fetchone()
        if row is None:
            raise AccountError(401, "Please sign in")
        return dict(row)

    def logout(self, token):
        with connect(self.auth) as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )


def make_accounts_handler(accounts, page):
    class Handler(BaseHTTPRequestHandler):
        def send(
            self, status, value,
            kind="application/json; charset=utf-8", headers=None
        ):
            payload = (
                json.dumps(value).encode()
                if kind.startswith("application/json")
                else value
            )
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(payload)

        def token(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                if "rackops_session" in cookie:
                    return cookie["rackops_session"].value
                return ""
            except CookieError:
                return ""

        def dispatch(self, post=False):
            try:
                host = "127.0.0.1:{}".format(self.server.server_port)
                if self.headers.get("Host") != host:
                    raise AccountError(
                        403, "Open RackOps using http://" + host
                    )
                path = urlsplit(self.path).path
                if not post and path == "/":
                    return self.send(
                        200, Path(page).read_bytes(),
                        "text/html; charset=utf-8"
                    )

                data = None
                if post:
                    if (
                        self.headers.get("Origin")
                        not in (None, "http://" + host)
                        or self.headers.get("X-RackOps-Request") != "1"
                    ):
                        raise AccountError(
                            403, "Request rejected. Refresh RackOps."
                        )
                    content_type = self.headers.get("Content-Type", "")
                    if content_type.split(";")[0].strip() != "application/json":
                        raise AccountError(415, "Use application/json")
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 16384:
                        raise AccountError(
                            413, "Request too large or empty"
                        )
                    data = json.loads(self.rfile.read(size))
                    if not isinstance(data, dict):
                        raise AccountError(400, "Expected a JSON object")

                if post and path in (
                    "/api/auth/register", "/api/auth/login"
                ):
                    user, token = accounts.authenticate(
                        data.get("username"),
                        data.get("password"),
                        path.endswith("/register"),
                    )
                    cookie = (
                        "rackops_session={}; HttpOnly; SameSite=Strict; "
                        "Path=/; Max-Age={}"
                    ).format(token, TTL)
                    return self.send(
                        200, {"username": user["username"]},
                        headers={"Set-Cookie": cookie}
                    )

                if post and path == "/api/auth/logout":
                    accounts.logout(self.token())
                    return self.send(
                        200, {"ok": True},
                        headers={
                            "Set-Cookie":
                            "rackops_session=; HttpOnly; SameSite=Strict; "
                            "Path=/; Max-Age=0"
                        },
                    )

                user = accounts.user(self.token())
                database = accounts.workspace(user)
                initialize_fiber(database)

                if not post:
                    if path == "/api/auth/me":
                        return self.send(
                            200, {"username": user["username"]}
                        )
                    readers = {
                        "/api/network": get_network,
                        "/api/disk": get_disk,
                        "/api/power": get_power,
                        "/api/fiber": get_fiber,
                        "/api/dashboard": get_dashboard,
                    }
                    if path in readers:
                        return self.send(200, readers[path](database))
                    if path in ("/api/devices", "/api/incidents"):
                        table = (
                            "devices"
                            if path == "/api/devices"
                            else "incidents"
                        )
                        with connect(database) as db:
                            rows = [
                                dict(row)
                                for row in db.execute(
                                    "SELECT * FROM " + table + " ORDER BY id"
                                )
                            ]
                        return self.send(200, rows)

                parts = path.strip("/").split("/")
                if (
                    len(parts) >= 3
                    and parts[:2] == ["api", "incidents"]
                    and re.fullmatch(r"INC-[0-9]{3}", parts[2])
                ):
                    incident_id = parts[2]
                    if (
                        not post and len(parts) == 4
                        and parts[3] == "report"
                    ):
                        report = build_report(
                            database, incident_id
                        ).encode()
                        return self.send(
                            200, report, "text/plain; charset=utf-8",
                            {
                                "Content-Disposition":
                                'attachment; filename="RackOps-{}-report.txt"'
                                .format(incident_id)
                            },
                        )

                    with connect(database) as db:
                        row = db.execute(
                            "SELECT * FROM incidents WHERE id=?",
                            (incident_id,),
                        ).fetchone()
                        if row is None:
                            raise AccountError(404, "Incident not found")

                        if not post and len(parts) == 3:
                            result = dict(row)
                            result["events"] = [
                                dict(r)
                                for r in db.execute(
                                    """SELECT * FROM events
                                       WHERE incident_id=? ORDER BY id""",
                                    (incident_id,),
                                )
                            ]
                            return self.send(200, result)

                        if (
                            post and len(parts) == 4
                            and parts[3] == "notes"
                        ):
                            note = data.get("note")
                            if (
                                not isinstance(note, str)
                                or not 1 <= len(note.strip()) <= 2000
                            ):
                                raise AccountError(
                                    400, "Enter a note of 1-2000 characters"
                                )
                            db.execute(
                                """INSERT INTO events
                                   (incident_id,kind,message,created_at)
                                   VALUES (?,?,?,?)""",
                                (
                                    incident_id, "note", note.strip(),
                                    datetime.now(timezone.utc).isoformat(),
                                ),
                            )
                        else:
                            raise AccountError(404, "Not found")
                    return self.send(201, {"ok": True})

                actions = {
                    "/api/network/actions": perform_action,
                    "/api/disk/actions": perform_disk_action,
                    "/api/power/actions": perform_power_action,
                    "/api/fiber/actions": perform_fiber_action,
                }
                if post and path in actions:
                    return self.send(
                        200, actions[path](database, data.get("action"))
                    )
                raise AccountError(404, "Not found")

            except (AccountError, ReportError) as error:
                self.send(error.status, {"error": str(error)})
            except (ValueError, UnicodeDecodeError):
                self.send(400, {"error": "Invalid request"})
            except sqlite3.Error:
                self.send(
                    503, {"error": "Database unavailable. Try again."}
                )

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch(post=True)

    return Handler
