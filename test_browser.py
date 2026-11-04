from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import unittest

from playwright.sync_api import sync_playwright, expect


PROJECT = Path(__file__).resolve().parent


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class RackOpsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(QuietHandler, directory=str(PROJECT))

        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            handler
        )
        cls.server_thread = Thread(
            target=cls.server.serve_forever,
            daemon=True
        )
        cls.server_thread.start()

        port = cls.server.server_address[1]
        cls.url = "http://127.0.0.1:{}/index.html".format(port)

        cls.playwright = sync_playwright().start()

        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception:
            cls.playwright.stop()
            cls.server.shutdown()
            cls.server.server_close()
            cls.server_thread.join()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls.playwright.stop()
            cls.server.shutdown()
            cls.server.server_close()
            cls.server_thread.join()

    def setUp(self):
        # Each test gets its own browser storage.
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.goto(self.url)

    def tearDown(self):
        self.context.close()

    def assert_counts(self, healthy, attention, opened, resolved):
        expected = {
            "healthyCount": healthy,
            "attentionCount": attention,
            "openCount": opened,
            "resolvedCount": resolved,
        }

        for element_id, value in expected.items():
            expect(
                self.page.locator("#" + element_id)
            ).to_have_text(str(value))

    def complete_disk(self):
        for step in range(4):
            self.page.locator(
                '[data-disk-step="{}"]'.format(step)
            ).click()

    def gather_network_evidence(self):
        for action in ["ip", "port", "ping"]:
            self.page.locator(
                '[data-net="{}"]'.format(action)
            ).click()

    def complete_network(self):
        self.gather_network_evidence()
        self.page.locator('[data-net="vlan"]').click()
        self.page.locator("#networkVerify").click()

    def test_fresh_dashboard(self):
        self.assert_counts(3, 2, 2, 0)
        expect(self.page.locator("#diskReport")).to_be_disabled()
        expect(self.page.locator("#networkReport")).to_be_disabled()

    def test_disk_requires_verification(self):
        for step in range(3):
            self.page.locator(
                '[data-disk-step="{}"]'.format(step)
            ).click()

        # Cleanup alone must not resolve the incident.
        self.assert_counts(3, 2, 2, 0)
        expect(self.page.locator("#diskStatus")).to_contain_text(
            "Verification required"
        )
        expect(self.page.locator("#diskReport")).to_be_disabled()

        self.page.locator('[data-disk-step="3"]').click()

        self.assert_counts(4, 1, 1, 1)
        expect(self.page.locator("#diskStatus")).to_contain_text(
            "Resolved"
        )
        expect(self.page.locator("#diskReport")).to_be_enabled()

    def test_network_blocks_change_without_evidence(self):
        self.page.locator('[data-net="vlan"]').click()

        expect(self.page.locator("#networkOutput")).to_contain_text(
            "More evidence required"
        )

        self.page.locator("#networkVerify").click()

        expect(self.page.locator("#networkOutput")).to_contain_text(
            "Recovery is not verified"
        )
        self.assert_counts(3, 2, 2, 0)
        expect(self.page.locator("#networkReport")).to_be_disabled()

    def test_network_fix_then_verification(self):
        self.gather_network_evidence()
        self.page.locator('[data-net="vlan"]').click()

        self.assert_counts(3, 2, 2, 0)
        expect(self.page.locator("#networkStatus")).to_contain_text(
            "Verification required"
        )
        expect(self.page.locator("#networkReport")).to_be_disabled()

        self.page.locator("#networkVerify").click()

        self.assert_counts(4, 1, 1, 1)
        expect(self.page.locator("#networkOutput")).to_contain_text(
            "Gateway 192.0.2.1: PASS"
        )
        expect(self.page.locator("#networkOutput")).to_contain_text(
            "Web server 192.0.2.21: PASS"
        )
        expect(self.page.locator("#deviceStatus")).to_have_text(
            "Healthy"
        )

    def test_reset_and_refresh_preserve_other_incident(self):
        self.complete_disk()
        self.complete_network()
        self.assert_counts(5, 0, 0, 2)

        self.page.locator("#networkReset").click()
        self.assert_counts(4, 1, 1, 1)

        self.page.reload()

        self.assert_counts(4, 1, 1, 1)
        expect(self.page.locator("#diskStatus")).to_contain_text(
            "Resolved"
        )
        expect(self.page.locator("#networkStatus")).to_contain_text(
            "Open"
        )

    def test_network_report_download(self):
        self.complete_network()

        with self.page.expect_download() as download_info:
            self.page.locator("#networkReport").click()

        download = download_info.value

        self.assertEqual(
            download.suggested_filename,
            "RackOps-INC-002-report.txt"
        )

        report = Path(download.path()).read_text(encoding="utf-8")

        self.assertIn("Status: Resolved", report)
        self.assertIn("access VLAN 30; expected VLAN 20", report)
        self.assertIn("gateway and web-server connectivity passed", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
