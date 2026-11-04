from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


PROJECT = Path(__file__).resolve().parent


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.buttons = []
        self.scripts = []
        self.inside_script = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        if "id" in attributes:
            self.ids.append(attributes["id"])

        if tag == "button":
            self.buttons.append(attributes)

        if tag == "script":
            self.inside_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside_script = False

    def handle_data(self, data):
        if self.inside_script:
            self.scripts.append(data)


class RackOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (PROJECT / "index.html").read_text(
            encoding="utf-8"
        )
        cls.page = PageParser()
        cls.page.feed(cls.html)
        cls.javascript = "\n".join(cls.page.scripts)

    def test_page_ids_are_unique(self):
        counts = Counter(self.page.ids)
        duplicates = [
            name for name, count in counts.items()
            if count > 1
        ]

        self.assertEqual(
            duplicates,
            [],
            "Duplicate IDs can connect code to the wrong element."
        )

    def test_javascript_targets_exist(self):
        targets = set(re.findall(
            r"""getElementById\(\s*["']([^"']+)["']\s*\)""",
            self.javascript
        ))

        self.assertTrue(
            targets,
            "No JavaScript element connections were found."
        )

        missing = targets - set(self.page.ids)

        self.assertEqual(
            missing,
            set(),
            "JavaScript references missing page elements."
        )

    def test_both_incident_panels_exist(self):
        required = {
            "diskStatus",
            "diskOutput",
            "diskTimeline",
            "diskReport",
            "diskReset",
            "networkStatus",
            "networkOutput",
            "networkTimeline",
            "networkVerify",
            "networkReport",
            "networkReset",
        }

        missing = required - set(self.page.ids)

        self.assertEqual(
            missing,
            set(),
            "An incident panel is missing required elements."
        )

    def test_disk_steps_are_complete_and_unique(self):
        steps = [
            button["data-disk-step"]
            for button in self.page.buttons
            if "data-disk-step" in button
        ]

        self.assertCountEqual(
            steps,
            ["0", "1", "2", "3"],
            "The disk lab needs exactly four action steps."
        )

    def test_network_actions_are_complete_and_unique(self):
        actions = [
            button["data-net"]
            for button in self.page.buttons
            if "data-net" in button
        ]

        self.assertCountEqual(
            actions,
            ["ip", "port", "ping", "renew", "enable", "vlan"],
            "A network inspection or corrective action is missing."
        )

    def test_reports_start_disabled(self):
        buttons = {
            button["id"]: button
            for button in self.page.buttons
            if "id" in button
        }

        for report_id in ["diskReport", "networkReport"]:
            with self.subTest(report=report_id):
                self.assertIn(report_id, buttons)
                self.assertIn(
                    "disabled",
                    buttons[report_id],
                    "Reports should start disabled before JavaScript loads."
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
