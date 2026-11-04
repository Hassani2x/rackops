# RackOps Architecture

RackOps is a browser-based data center troubleshooting simulation.

## Components

| Component | Responsibility |
| --- | --- |
| HTML | Defines the rack, device details, and incident panels |
| CSS | Controls layout, colors, and device status indicators |
| JavaScript | Handles inspections, simulated changes, and recovery verification |
| localStorage | Saves progress in the current browser |
| Report export | Generates downloadable text reports |
| Python tests | Checks HTML structure and element connections |
| GitHub Actions | Runs the structure checks on pushes and pull requests |
| GitHub Pages | Hosts the public website |

## Incident State

The disk incident progresses through five stages:

1. Alert opened
2. Disk usage inspected
3. Expired logs identified
4. Cleanup completed
5. Recovery verified

The network incident tracks evidence separately from the fix:

- IP configuration inspected
- Switch port inspected
- Gateway connectivity tested
- VLAN correction applied
- Recovery verified

The network lab requires all three evidence checks before accepting the VLAN correction.

## Device Health

SRV-02 remains in Warning until disk recovery is verified.

SRV-03 starts with a Network outage. Applying the VLAN fix changes its status to Verification pending. Successful verification changes it to Healthy.

## Saved Progress

The browser stores two separate entries:

- rackops.incident.v1: disk progress and selected device
- rackops.network.v1: network evidence, fix, and resolution state

Saved data is validated before loading. Missing or invalid data starts a fresh state for the affected lab.

Resetting one incident preserves the other incident's progress.

## Reports

Reports become available after an incident is resolved.

JavaScript creates a text file containing the findings, corrective action, verification result, follow-up, and timeline.

## Testing

Run the six structure checks locally:

```bash
python3 test_rackops.py
```

GitHub Actions runs the same checks automatically.

These tests inspect HTML structure. They do not execute JavaScript or verify browser behavior. Incident behavior is currently checked manually.

## Simulation Boundary

All device information, command outputs, and connectivity results are predefined simulation data.

RackOps has no backend, user accounts, or live device connections. Progress is stored locally in each browser.
