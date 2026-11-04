# RackOps

<img width="1408" height="786" alt="rackops-demo" src="https://github.com/user-attachments/assets/e5370adb-dd7f-42a7-bd72-bf27c0644b1c" />

An interactive data center operations training lab built with HTML, CSS, and JavaScript.

Explore a simulated rack, investigate incidents, gather evidence, apply corrective actions, and verify recovery.

## Live Demo

[Try RackOps](https://hassani2x.github.io/rackops/)

## Features

- Clickable rack inventory with five devices
- Device roles, rack locations, lab IP addresses, and simulated health states
- Two troubleshooting incidents
- Evidence requirements before changing the network configuration
- Recovery verification before incidents can be resolved
- Timestamped incident timelines
- Saved progress using browser localStorage
- Downloadable text reports for resolved incidents
- Separate reset buttons for each lab
- Responsive dark interface

## Incident 1: High Disk Usage

SRV-02 triggers a disk-usage warning.

1. Inspect disk usage and confirm /var is 92% full.
2. Inspect log files and identify 30 GB of expired rotated logs.
3. Perform the approved simulated cleanup.
4. Verify disk usage has dropped to 62%.
5. Download the completed incident report.

The cleanup preserves active logs and database files. SRV-02 remains in Warning until recovery is verified.

Follow-up: configure and test log retention to prevent recurrence.

## Incident 2: Network Outage

SRV-03 cannot reach its gateway or other lab servers.

Choose inspections to gather evidence:

- Compare the IP address and gateway with the expected configuration.
- Inspect the switch port's administrative state, physical link, and access VLAN.
- Test gateway connectivity.

The evidence identifies an incorrect access VLAN: VLAN 30 instead of the planned VLAN 20.

The lab requires all three inspections before allowing the VLAN change. After applying the fix, verify gateway and web-server connectivity to resolve the incident.

Alternative actions explain why renewing a static IP configuration or enabling an already enabled port does not fix this scenario.

Follow-up: audit switch-port assignments against the network plan.

## Run Locally

Download this repository and open index.html in a modern web browser.

No installation, Python server, or external dependencies are required.

Use the same browser and file location when testing saved progress. Browser settings may prevent local storage.

## How It Works

- HTML defines the page structure.
- CSS styles the rack, device details, and incident panels.
- JavaScript controls inspections, corrective actions, verification, and device states.
- localStorage saves incident progress and timelines in the browser.
- Browser-generated text files export completed incident reports.
- GitHub Pages hosts the public demo.

## Saved Progress

Each incident has its own saved state.

Refreshing the page restores progress when browser storage is available. Resetting one lab restarts that incident while preserving the other incident.

Local files and the hosted website use separate browser storage. Progress is not synchronized between them or between devices.

## Manual Verification

- Select each device and confirm its details update.
- Complete the disk incident and confirm SRV-02 becomes Healthy.
- Attempt a network VLAN change before gathering all evidence and confirm it is deferred.
- Verify network recovery before applying the fix and confirm the incident remains open.
- Gather all network evidence, apply the VLAN fix, and verify both connectivity checks pass.
- Confirm SRV-03 becomes Healthy after verification.
- Refresh during an incident and after resolution to check saved progress.
- Download both reports and review their findings and timelines.
- Reset each lab and confirm its initial alert returns.

These are manual checks. Automated tests have not yet been added.

## Limitations

RackOps is a simulated training lab.

- Device health, command output, and connectivity results are predefined.
- No live devices are monitored.
- No system commands run and no real files are deleted.
- The network lab models one predefined VLAN fault.
- Saved progress is stored in the current browser.
- Clearing browser storage removes saved progress.
- Reports describe simulated exercises, not production incidents.

## Planned Improvements

- Automated tests for incident behavior
- Additional troubleshooting scenarios
- Backend inventory storage
- Architecture documentation
- Recorded project walkthrough
