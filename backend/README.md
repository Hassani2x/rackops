# RackOps Backend

A local data center troubleshooting simulation built with Python,
SQLite, HTML, CSS, and JavaScript.

## Start

Requires Python 3.9 or newer. No additional packages are required.

In Terminal:

    cd ~/Desktop/rackops-backend
    python3 run.py

Open http://127.0.0.1:8001 in your browser.
Keep Terminal open while using the app.
Press Control+C to stop the server.

## Run automated tests

    python3 run.py --test

Tests use temporary databases and do not reset your saved progress.

## Features

- Five simulated inventory devices.
- Disk usage, VLAN mismatch, and power redundancy incident labs.
- Evidence required before approved corrective actions.
- Recovery verification required before incident resolution.
- Investigation notes and timestamped event timelines.
- SQLite persistence across browser refreshes and server restarts.
- Dashboard counts read from the database.
- Downloadable reports for resolved incidents.
- Independent lab resets that retain notes and history.

## Incident labs

### INC-001: High Disk Usage

Inspect the filesystem, files, and database service.
Perform approved expired-log cleanup, preserving active logs and
database files. Verify disk usage and service health before resolving.

### INC-002: Network Outage

Inspect IP configuration and switch-port settings, then test connectivity.
Correct the access VLAN from 30 to the planned VLAN 20.
Verify gateway and web-server connectivity before resolving.

### INC-003: Power Redundancy Lost

Inspect the PSUs, independent power feeds, and event log.
Preserve the working PSU B while simulating approved replacement of PSU A.
Verify power health and restored redundancy before resolving.

## Code organization

- run.py: standard startup and test commands.
- server.py: database schema, inventory, incidents, notes, and base HTTP routes.
- network_app.py: network simulation state and action rules.
- disk_app.py: disk simulation state and action rules.
- power_app.py: power simulation state and action rules.
- dashboard_app.py: database dashboard counts.
- reports_app.py: incident report generation and downloads.
- static/reports.html: current integrated browser interface.
- test_*.py: automated tests.

Earlier HTML pages remain as development milestones.
Use run.py to launch the current integrated version.

## Saved data

The app creates data/rackops.sqlite3 automatically.
Keep this file to preserve local progress and notes.
Do not upload the data folder to GitHub.

The backend starts with its own records. It does not import progress
from the earlier static demo's browser storage.

## Current scope

All equipment states, checks, and changes are simulated.
There are no live device connections or user accounts yet.
This version runs locally on 127.0.0.1.

The existing GitHub Pages demo remains a separate static version.
GitHub Pages cannot run this Python backend.

## Next milestones

- User accounts and separate progress for each user.
- Fiber connectivity and server boot incident labs.
- Public backend hosting and deployment.
