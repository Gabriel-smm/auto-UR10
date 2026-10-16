# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Python control of a second-hand **Universal Robots UR10** (CB3 controller, PolyScope 3.15.6) on a Ready Robotics TaskMate R10 cart, with a **Robotiq 2F-85** gripper and an **Intel RealSense D455** camera.

- **Arm:** `ur_rtde` over Ethernet. Robot at `192.168.0.1`; control computer on the same `/24` subnet with no default gateway.
- **Gripper:** Modbus RTU over RS-485 through the FTDI adapter inside the cart base and the TeachMate. Slave address 9, 115200 baud, 8N1. Driven directly by [`scripts/gripper.py`](scripts/gripper.py), with no URCap.
- **Safety:** the UR controller keeps real-time control and enforces safety planes and joint position limits. ForgeOS is not used; the robot runs native PolyScope.
- **Dependencies:** [`requirements.txt`](requirements.txt) (`ur_rtde`, `pyserial`). Run scripts from the repository root.

Read these before changing anything; do not duplicate their content here:

- [`README.md`](README.md): overview, hardware, architecture, repository map.
- [`docs/setup.md`](docs/setup.md): lab operating procedure, network and serial setup, safety checklist, troubleshooting, Modbus reference.
- [`docs/commissioning.md`](docs/commissioning.md): how the cell was brought back into service, including the wrong turns and lessons.

### Roadmap

Next goals: **RealSense D455 vision** (perception for picking) and **autonomous pick-and-place**, building on the arm + gripper smoke test in [`scripts/pick_test.py`](scripts/pick_test.py).

## Git rules

- **NEVER push or pull without explicit authorization.** This covers `git push`, `git pull`, merging fetched changes, and opening PRs. Ask each time; approval for one push does not cover the next.
- **Commit regularly.** Make small, logical commits after each working unit of change, with clear messages. Do not let large amounts of uncommitted work build up.
- **Branches need approval.** Feature and task work goes on its own branch, but ask the user to authorize the branch and choose its name before creating it.
- Never commit robot configuration backups, PolyScope programs or installations (`*.urp`, `*.installation`), or logs. These are already in `.gitignore`.

### Pull request descriptions

Use these sections, in this order:

- **Stacking note** (only if the PR is based on another branch): which PR it depends on and that it retargets to `main` once that one merges.
- **Summary**: one bullet per changed file or area, bold name first. Give the concrete values (limits, speeds, poses, checksums), not just "updated config". Include the docs that changed.
- **Points to check on the pendant** (when relevant): anything that depends on robot-side configuration or that the code cannot confirm on its own.
- **Test plan**: a checklist, grouped from least to most risky, each item naming the exact command and the expected result:
  - `[ ] Offline:` checks that need no hardware (dry runs with stand-in objects, maths round-trips, deliberately injected failures that must be rejected).
  - `[ ] Hardware, read-only:` RTDE receive-only or status checks, with what to compare against on the pendant.
  - `[ ] Hardware:` motion runs, in the order to run them.

  Tick an item only once it has actually passed. Hardware items are ticked after the user confirms the run, and passing them is when "unverified" notes in the docs get removed.

## Documentation is a core deliverable

Technical documentation is as important as the code in this project. A task is not done until the docs reflect it.

- Any change to behavior, usage, hardware setup, wiring, network, PolyScope configuration or safety must update the relevant docs **in the same commit**:
  - `README.md`: overview, hardware table, architecture diagram, Repository table.
  - `docs/setup.md`: procedures, script usage, troubleshooting, reference tables.
  - `docs/commissioning.md`: engineering history, including what went wrong and the lessons learned.
- A new script gets a row in the README Repository table and a section under "Running the scripts" in `docs/setup.md`.
- Match the existing style: plain and precise, tables for settings and references, cross-links between documents.
- Document only verified facts. Mark anything not yet confirmed on the hardware as unverified (for example, Modbus frames in `docs/setup.md` are checked against `gripper.frame()`).

## Hardware safety

- **Ask before running anything that talks to the hardware**, including read-only checks (`gripper.py status`, RTDE receive-only reads) and especially motion (`gripper.py activate|open|close`, `pick_test.py`, anything using `RTDEControlInterface`). Approval for one run does not cover the next.
- When asking, remind the user to keep a hand on the emergency stop and not to run a PolyScope program at the same time. Gripper activation moves the fingers fully.
- New motion code: test read-only first, default to slow and small moves, and release the robot with `control.stopScript()` in a `finally` block.
- Never change robot-side configuration (IP, safety settings, installation) from code. Trust the pendant over written notes.

## Code conventions

- Follow the minimal style of [`scripts/gripper.py`](scripts/gripper.py): a module docstring with usage, configuration constants grouped in sections at the top, small functions, `try`/`finally` cleanup of serial and RTDE connections.
- Add new dependencies to `requirements.txt` and mention them in the docs.
