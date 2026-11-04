## Testing

RackOps includes 12 automated tests.

### Structure Checks

Six Python tests check unique element IDs, JavaScript element references, required incident elements, action buttons, and initial report-button states.

Run them with:

```bash
python3 test_rackops.py
```

### Browser Tests

Six Playwright tests run Chromium and check:

- Initial dashboard counts
- Disk recovery verification requirements
- Network changes blocked without evidence
- VLAN correction followed by recovery verification
- Independent incident reset and saved progress after refresh
- Network report download and contents

With the project's virtual environment activated, run:

```bash
python test_browser.py
```

Each browser test uses isolated storage and a temporary local server.

### GitHub Actions

The workflow runs both test files on pushes and pull requests.

It uses Python 3.12, Playwright 1.60.0, and Ubuntu 24.04. The Ubuntu version is pinned for compatibility.

GitHub Pages deployment runs separately. Passing tests does not guarantee that publishing has completed.
