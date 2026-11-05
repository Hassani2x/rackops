from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from server import ROOT, DATABASE, connect
from power_app import initialize_power, PowerHandler


def get_dashboard(path):
    with connect(path) as db:
        row = db.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(status = 'open'), 0) AS open,
                COALESCE(SUM(status = 'verification_required'), 0) AS awaiting,
                COALESCE(SUM(status = 'resolved'), 0) AS resolved,
                (SELECT COUNT(*) FROM devices) AS devices
            FROM incidents
        """).fetchone()
        return dict(row)


class DashboardHandler(PowerHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            return self.send(
                200,
                (ROOT / "static/dashboard.html").read_bytes(),
                "text/html; charset=utf-8",
            )
        if path == "/api/dashboard":
            return self.send(200, get_dashboard(DATABASE))
        return super().do_GET()


if __name__ == "__main__":
    initialize_power(DATABASE)
    server = ThreadingHTTPServer(("127.0.0.1", 8001), DashboardHandler)
    print("RackOps dashboard: http://127.0.0.1:8001", flush=True)
    print("Keep Terminal open. Control+C stops the server.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
