"""Start RackOps or run its automated tests."""
import argparse
import sys
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="RackOps local backend")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run automated tests without starting the server",
    )
    args = parser.parse_args()

    if args.test:
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(PROJECT),
            pattern="test_*.py",
            top_level_dir=str(PROJECT),
        )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1

    from server import DATABASE
    from accounts_app import Accounts, make_accounts_handler

    page = PROJECT / "static" / "accounts.html"
    if not page.is_file():
        print("Missing static/accounts.html. Complete the accounts setup first.")
        return 1

    accounts = Accounts(PROJECT / "data", DATABASE)
    handler = make_accounts_handler(accounts, page)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 8001), handler)
    except OSError as error:
        print("Could not start RackOps:", error)
        print("If another RackOps server is running, stop it with Control+C.")
        return 1

    print("RackOps: http://127.0.0.1:8001", flush=True)
    print("Database:", DATABASE, flush=True)
    print("Keep this Terminal open. Control+C stops the server.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nRackOps stopped. Saved progress remains in the database.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
