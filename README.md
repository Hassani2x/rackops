# RackOps

<img width="1408" height="786" alt="rackops-demo" src="https://github.com/user-attachments/assets/e5370adb-dd7f-42a7-bd72-bf27c0644b1c" />



An interactive data center operations training lab built with HTML, CSS, and JavaScript.

Explore a simulated rack, investigate a disk-usage alert, perform an approved simulated cleanup, and verify recovery.

## Features

- Clickable rack inventory with five devices
- Device roles, rack locations, lab IP addresses, and simulated health states
- Guided disk-usage incident with four troubleshooting steps
- Timestamped incident timeline
- Saved progress using browser localStorage
- Downloadable incident report after recovery verification
- Reset button to repeat the exercise
- Responsive dark interface

## Run Locally

Download this repository and open index.html in a modern web browser.

No installation, Python server, or external dependencies are required.

Use the same browser and file location when testing saved progress. Browser privacy settings may prevent local storage.

## Incident Walkthrough

1. Inspect disk usage: confirm /var is 92% full.
2. Inspect log files: identify 30 GB of expired rotated logs.
3. Remove rotated logs: simulate the approved cleanup while preserving active logs and database files.
4. Verify recovery: confirm disk usage is 62%, below the 90% warning threshold.
5. Download the incident report.

The device remains in Warning until recovery is verified.

## How It Works

- HTML defines the page structure.
- CSS styles the rack and incident panels.
- JavaScript renders device details and controls incident stages.
- localStorage saves the current stage, selected device, and timeline.
- A browser-generated text file exports the completed incident report.

## Limitations

This is a simulated training lab.

- Device health and command output are predefined.
- No live devices are monitored.
- No system commands run and no real files are deleted.
- Saved progress belongs to the current browser and is not synchronized between devices.
- Clearing browser storage removes saved progress.
- One incident scenario is currently available.

## Manual Checks

- Select each device and confirm its details update.
- Complete the four incident steps in order.
- Refresh midway and confirm progress is restored.
- Verify recovery and confirm SRV-02 becomes Healthy.
- Download the report and check its findings and timeline.
- Reset the lab and confirm the initial warning returns.

## Planned Improvements

- Additional troubleshooting scenarios
- Backend inventory storage
- Automated tests
- Public browser demo
