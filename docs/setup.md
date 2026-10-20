# Lab setup and operating procedure

How to set up and run the UR10 cell (UR10 on CB3, PolyScope 3.15.6, Ready Robotics TaskMate R10 cart, Robotiq 2F-85 gripper) from a control computer. For how the cell was brought back into service, see [commissioning.md](commissioning.md). For an overview of the project, see the [README](../README.md).

## Contents

- [Requirements](#requirements)
- [Network configuration](#network-configuration)
- [Gripper serial link](#gripper-serial-link)
- [Required PolyScope configuration](#required-polyscope-configuration)
  - [Safety configuration](#safety-configuration)
- [Pre-session safety checklist](#pre-session-safety-checklist)
- [Start-up procedure](#start-up-procedure)
- [Running the scripts](#running-the-scripts)
- [Simulation (URSim)](#simulation-ursim)
- [Shutdown](#shutdown)
- [Troubleshooting](#troubleshooting)
- [Reference: Modbus frames](#reference-modbus-frames)

## Requirements

- Python 3, with the dependencies installed from the repository root:

  ```bash
  pip install -r requirements.txt
  ```

- A computer with an Ethernet port (for the robot) and a free USB port (for the gripper).
- For the simulator only: Docker (see [Simulation (URSim)](#simulation-ursim)).

## Network configuration

| Device | Address |
|---|---|
| Robot | static `192.168.0.1`, mask `255.255.255.0` |
| Control computer | static address on the same subnet, for example `192.168.0.20/24`, **no default gateway** |

Leaving the gateway empty on the wired interface means internet traffic keeps going over Wi-Fi.

Example with NetworkManager on Linux, where `<interface>` is the name of the computer's wired interface:

```bash
sudo nmcli con add type ethernet ifname <interface> con-name ur10 \
  ipv4.method manual ipv4.addresses 192.168.0.20/24 ipv4.never-default yes
sudo nmcli con up ur10
ping -c 3 192.168.0.1
```

Always confirm the robot's IP on the pendant (**Setup Robot → Network**) rather than trusting written notes. If the two disagree, change the computer's settings, not the robot's.

## Gripper serial link

The gripper is reached over RS-485 through the USB-to-RS-485 adapter inside the cart base and the TeachMate.

| Setting | Value |
|---|---|
| Protocol | Modbus RTU |
| Slave address | 9 |
| Serial | 115200 baud, 8N1 |
| Port | detected automatically by `gripper.py`: `/dev/serial/by-id/*RS-485*`, falling back to `/dev/ttyUSB0` |
| Position range (observed) | open ≈ 3, closed ≈ 228 of 255 |

On Linux, add your user to the `dialout` group so the port can be used without `sudo`:

```bash
sudo usermod -aG dialout $USER
```

Log out and back in for the change to take effect.

## Required PolyScope configuration

- **Fieldbus off.** EtherNet/IP and PROFINET must be disabled in the **Installation** tab, and the installation saved as a new installation. Fieldbus settings left over from ForgeOS otherwise raise error `C207A0` and block RTDE.
- **Safety boundaries.** Safety planes and joint position limits are configured as the cell's safety boundaries. On a CB3, safety planes restrict only the TCP, not the elbow, wrists or tool body, which is why joint limits are also needed. The values are listed under [Safety configuration](#safety-configuration).
- **Payload and TCP.** These must match the tool actually mounted. For the 2F-85: payload **1.8 kg**, TCP `rough_robotiq` at 165.8 mm along tool Z (**Installation → TCP Configuration**). If they are not set for the current tool, keep speeds low.

### Safety configuration

From the active installation, exported from the pendant as `miniro_2safety.installation` (safety checksum CRC `313597321`). The same values are held as constants in [`scripts/safety.py`](../scripts/safety.py), which the motion scripts check against before moving. The controller enforces the limits either way; the software checks only refuse a move earlier, with a margin.

Exported installations go in `backups/`, which is ignored by git: never commit them. After any change on the pendant, export the installation to a USB stick, copy it into `backups/` and run `python scripts/safety.py compare backups/<file>.installation`. Update `safety.py` and this section if it reports differences.

**General limits**

| Limit | Normal | Reduced |
|---|---|---|
| TCP speed | 1.5 m/s | 0.75 m/s |
| Force | 150 N | 120 N |
| Power | 300 W | 200 W |
| Momentum | 25 kg·m/s | 10 kg·m/s |
| Joint speed | 131.5°/s base and shoulder, 191.5°/s elbow and wrists | same |

Reduced mode has no trigger configured (no reduced-mode safety input), so the robot runs in Normal mode.

**Joint position limits** (enabled on all joints)

| Joint | Normal | Reduced |
|---|---|---|
| Base | −363° … 363° | −363° … 363° |
| Shoulder | −363° … **−51°** | −363° … 363° |
| Elbow, Wrist 1–3 | −363° … 363° | −363° … 363° |

Only the shoulder is narrowed, and only in Normal mode. The installation stores each limit as revolutions·2π + angle. For example, shoulder max = −1·2π + 5.3931 rad = −51.0°.

> **Unverified:** whether the pendant displays the shoulder limit as −51° or as −54° plus a 3° tolerance. The other joints' ±363° suggests the stored values include such a tolerance.

**Safety planes** (mode: Normal and Reduced)

| Plane | Feature | Normal n (base frame) | d | Displacement | Limit surface |
|---|---|---|---|---|---|
| `backwall` | `backwall` | (0.0001, 0.9972, 0.0743) | 344.2 mm | 10 mm | behind the robot, y ≈ −345 mm |
| `leftwall` | `left_wall` | (−0.9791, 0.1172, −0.1663) | 733.3 mm | 20 mm | x ≈ +750 mm |
| `Base` | `base` | (−0.0007, 0.0000, 1.0000) | 164.1 mm | 90 mm | below the base, z ≈ −164 mm |

Planes 3–7 and the tool orientation limit are disabled.

- **Side convention.** Each plane comes from a plane feature taught with three points. The feature's +Z, by the right-hand rule over the taught points, points into the **prohibited** side. The installation stores the opposite direction as `planeNormal`, so n points to the **allowed** side. For a point p in the base frame, the signed margin is **n·p + d**: positive means allowed, zero means on the limit. The robot base (p = 0) is inside all three planes.
- **Displacement.** `d` already includes the displacement. For each plane, `d` equals the taught surface's offset plus the displacement, so the limit sits 10, 20 and 90 mm beyond the taught points, **on the prohibited side**. If the taught points were on the physical wall and table, the checked point can reach past them by that much.
- **Checked point.** The planes restrict a single point: the flange plus 162.8 mm along tool Z, which was the TCP active when the planes were defined. The active TCP is now 165.8 mm, so the checked point is 3 mm closer to the flange than the TCP that `getActualTCPPose()` reports.

Verified on the robot: the margins from `python scripts/safety.py watch` match where the pendant stops the robot at a plane.

**Safety I/O**

| Function | Signals |
|---|---|
| Emergency stop input | configurable inputs 0 and 1 (named `E-Stop`) |
| System emergency stop output | configurable outputs 0 and 1 (named `E-Stop`) |
| Reduced mode, safeguard reset, 3-position enabling, operational mode | not assigned |

## Pre-session safety checklist

- [ ] Cart casters locked; floor flat and solid.
- [ ] Reach envelope (about 1300 mm radius) clear of people and equipment.
- [ ] Emergency stop located and tested.
- [ ] Hair and loose clothing tied back; hands clear of the gripper (activation moves the fingers fully).

## Start-up procedure

1. Confirm the arm and cart are secure, then connect the robot cable and mains. Make sure the cart is powered on.
2. Power on from the teach pendant and wait for boot (about 1 min).
3. On the **Initialization** screen, check that payload and installation match the physical setup.
4. Press **ON**: the robot goes to Idle. Press **START**: the brakes release.
5. Optional: check motion with Freedrive or the **Move** tab.
6. Connect the Ethernet and gripper USB cables to the control computer.
7. Bring up the network and check the link: `ping 192.168.0.1`.
8. Run `python scripts/gripper.py status`. A dictionary means the gripper is answering; `None` means no reply.
9. Run `python scripts/gripper.py activate` if the gripper has been power-cycled.
10. Run the script. Keep a hand on the emergency stop, start slow and small, and do not run a PolyScope program at the same time, because `RTDEControlInterface` takes over the robot while connected.

## Running the scripts

Run the commands from the repository root.

The scripts that talk to the robot (`pick_test.py`, `pick_place.py`, `show_pose.py`, `safety.py watch`) target the real robot at `192.168.0.1` by default. They also take `--sim` to target the [simulator](#simulation-ursim) instead, and print the target before connecting (see [`scripts/robot.py`](#scriptsrobotpy)).

### `scripts/gripper.py`

Minimal Modbus RTU driver for the 2F-85, usable from the command line or as a module.

```bash
python scripts/gripper.py status     # default: print the status dict, or None if no reply
python scripts/gripper.py activate   # reset, then activate; required after every power cycle
python scripts/gripper.py open
python scripts/gripper.py close
```

The status dictionary has the keys `act` (gACT), `goto` (gGTO), `sta` (gSTA), `obj` (gOBJ), `fault`, `pos` and `current`.

As a module (with `scripts/` on the Python path):

| Function | Purpose |
|---|---|
| `connect(port=PORT)` | Open the serial link (115200 baud, 0.3 s timeout). |
| `status(s)` | Read the status registers; returns a dict, or `None` on no reply or bad CRC. |
| `activate(s, secs=15)` | Reset, then activate; waits until gSTA = 3. The fingers open and close fully. |
| `move(s, pos, speed=64, force=0, secs=8)` | Go to `pos` (0 = open, 255 = closed) and wait until the motion ends or an object is hit. |
| `open_(s)`, `close(s)` | Shortcuts for `move` to `POS_OPEN` and `POS_CLOSED`. |
| `write(s, action, pos, speed, force)` | Write the three output registers at `0x03E8`. |
| `wait(s, test, secs)` | Poll the status until `test(status)` is true or time runs out. |
| `frame(body)`, `crc(data)` | Build a Modbus frame: slave address + body + CRC-16. |

```python
import gripper as g
s = g.connect()
g.activate(s)
print(g.close(s))
s.close()
```

### `scripts/pick_test.py`

Arm and gripper smoke test, run against the robot at `192.168.0.1`:

```bash
python scripts/pick_test.py
python scripts/pick_test.py --sim     # simulator at 127.0.0.1, with fake_gripper.py
```

It performs this sequence:

1. Reads the gripper status (exits if the gripper does not answer) and activates it if needed.
2. Records the current TCP pose and runs `safety.preflight` on the lift (see `pick_place.py` step 3). It exits without moving if any check fails.
3. Opens the gripper, lifts the TCP 2 cm along base Z (`moveL` at 0.05 m/s, 0.1 m/s²), closes, then opens again.
4. Returns to the start pose and prints the start and end TCP poses.
5. Calls `stopScript()` to release the robot.

The end pose should match the start pose to within about 0.1 mm.

### `scripts/show_pose.py`

Prints the robot's current position: the TCP pose in the base frame and the six joint angles. It is read-only: it uses `RTDEReceiveInterface` only, so it does not take over the robot and can run while jogging with Freedrive or the **Move** tab.

```bash
python scripts/show_pose.py                     # print once
python scripts/show_pose.py --watch             # refresh in place until Ctrl-C
python scripts/show_pose.py --watch --rate 2    # refresh rate in Hz (default 10)
python scripts/show_pose.py --ip 192.168.0.1    # robot IP (default 192.168.0.1)
python scripts/show_pose.py --sim               # simulator at 127.0.0.1
```

The first line of output is the target, `TARGET: REAL ROBOT (192.168.0.1)` or `TARGET: SIMULATOR (127.0.0.1)`.

Example output:

```
TCP pose (base frame)
  X   -123.45 mm    Rx   0.1234 rad    Roll   -179.99°
  Y    456.78 mm    Ry  -3.1234 rad    Pitch    -0.90°
  Z    321.00 mm    Rz   0.0012 rad    Yaw    -175.48°
  Python: [-0.12345, 0.45678, 0.32100, 0.1234, -3.1234, 0.0012]

Joints
  Base        12.34°   Shoulder   -90.00°   Elbow       85.10°
  Wrist 1    -85.00°   Wrist 2    -90.00°   Wrist 3      0.00°
```

| Field | Unit | Notes |
|---|---|---|
| X, Y, Z | mm | TCP position in the base frame. |
| Rx, Ry, Rz | rad | Rotation vector, the representation used by `ur_rtde` and the pendant. |
| Roll, Pitch, Yaw | degrees | Computed from the rotation vector, UR convention R = Rz(yaw)·Ry(pitch)·Rx(roll). |
| Python | m, rad | The TCP pose as `[x, y, z, rx, ry, rz]`, the format `moveL` takes. Paste it directly into a script, for example as `TARGET` in `pick_place.py`. |
| Joints | degrees | From `getActualQ()`. |

Verified on the robot: the values match the pendant's **Move** tab (Base feature).

### `scripts/pick_place.py`

Moves from the current position to a fixed target pose, closes the gripper, and returns to the start. Run against the robot at `192.168.0.1`:

```bash
python scripts/pick_place.py
python scripts/pick_place.py --sim    # simulator at 127.0.0.1, with fake_gripper.py
```

It performs this sequence:

1. Reads the gripper status (exits if the gripper does not answer) and activates it if needed.
2. Records the current TCP pose as the start, and prints the start, the target and the distance between them.
3. Exits without moving if the start is more than `MAX_DIST` (1500 mm) from the target, if `isPoseWithinSafetyLimits` rejects the target, or if `safety.preflight` reports a problem. `preflight` checks the following, and prints the smallest plane margin and joint headroom along the path:
   - the active TCP is `rough_robotiq` (165.8 mm);
   - the speed is no higher than the Reduced-mode TCP limit (0.75 m/s);
   - along the straight-line path, sampled at 50 points, the plane-checked point stays at least 30 mm inside every [safety plane](#safety-configuration), and every joint stays at least 3° from its limit (joint angles from the controller's inverse kinematics). The return leg follows the same line, so one check covers both moves.
4. Waits for Enter (Ctrl-C aborts).
5. Opens the gripper, moves to the target (`moveL` at 0.1 m/s, 0.15 m/s²), closes the gripper (prints `Object gripped` if it stopped on an object), and returns to the start.
6. Prints the end pose and calls `stopScript()` to release the robot. The gripper stays closed.

Configured target (`TARGET`, base frame):

| X | Y | Z | Rx | Ry | Rz |
|---|---|---|---|---|---|
| -0.98 mm | 573.37 mm | -83.23 mm | -1.9014 rad | -2.3362 rad | -0.1152 rad |

Both moves are straight lines in Cartesian space, so the path between the start and the target must be clear. To change the target, jog the robot to the new pose, read it with `python scripts/show_pose.py`, and paste its `Python:` line into `TARGET`.

### `scripts/safety.py`

The cell's safety configuration as constants (see [Safety configuration](#safety-configuration)), plus the checks the motion scripts run before moving. It does not command motion.

```bash
python scripts/safety.py show                                        # print the limits (default)
python scripts/safety.py compare backups/miniro_2safety.installation # check an exported installation
python scripts/safety.py watch                                       # live plane margins and joint headroom
python scripts/safety.py watch --rate 2 --ip 192.168.0.1
python scripts/safety.py watch --sim                                 # simulator at 127.0.0.1
```

- `compare` reads the safety settings, the active TCP and the payload from the gzipped XML of a `.installation` file. It prints the safety checksum and every value that differs from the constants. The exit status is 1 if anything differs.
- `watch` is read-only (`RTDEReceiveInterface` only), like `show_pose.py`. It shows the safety mode, the signed distance to each plane, and each joint's distance to its limit, and marks values inside the software margins. It assumes that the active TCP is `rough_robotiq` (165.8 mm).

As a module:

| Name | Purpose |
|---|---|
| `plane_margins(tcp_pose)` | Signed distance (m) from the plane-checked point to each plane; positive means allowed. |
| `joint_headroom(q)` | Distance (rad) from each joint to its nearer limit. |
| `scan_move(start, target, q_start, ik)` | Smallest plane margin and joint headroom along a straight-line (`moveL`) move, sampled at `PATH_STEPS` points. Joint angles come from `ik`, for example `RTDEControlInterface.getInverseKinematics`. |
| `check_move(start, target, q_start, ik)` | List of problems: any plane closer than `PLANE_MARGIN` (30 mm) or joint closer than `JOINT_MARGIN` (3°) along the path. |
| `preflight(control, start, target, q_start, speed)` | What the motion scripts call before moving: checks the active TCP, the speed and `check_move`, prints the smallest margins, and returns the list of problems. |
| `parse_installation(path)`, `compare(path)` | Read an exported installation; compare it with the constants. |

### `scripts/robot.py`

Chooses the target for every script that talks to the robot: the real UR10 or the [simulator](#simulation-ursim). It is a module, not a command.

| Input | Target | Gripper module |
|---|---|---|
| nothing | real robot, `192.168.0.1` | `gripper.py` |
| `--ip <address>` | real robot at that address | `gripper.py` |
| `--sim` | simulator, `127.0.0.1` | `fake_gripper.py` |
| `--ip 127.0.0.1` or `--ip localhost` | simulator, `127.0.0.1` | `fake_gripper.py` |
| environment `UR10_SIM=1` | simulator, `127.0.0.1` | `fake_gripper.py` |
| `UR10_SIM=0` or unset | as if not set | |

Rejected with an error, before anything connects:

- `--sim` or `UR10_SIM=1` with any other `--ip`, for example `--sim --ip 192.168.0.1`;
- `UR10_SIM` set to anything other than `1`, `0` or empty.

Before connecting, it prints `TARGET: SIMULATOR (127.0.0.1)` or `TARGET: REAL ROBOT (192.168.0.1)`. Check this line before every motion run, especially when `UR10_SIM` may be set in the shell.

| Function | Purpose |
|---|---|
| `add_args(parser)` | Add `--sim` and `--ip` to an `argparse` parser. |
| `select(parser, args)` | Apply the rules above, print the target, and return `(ip, sim)`. |
| `gripper(sim)` | The gripper module for the target: `fake_gripper` or `gripper`. |

### `scripts/fake_gripper.py`

Stand-in for `gripper.py`, used by the motion scripts with `--sim`, because the [simulator](#simulation-ursim) does not simulate the gripper. It has the same public functions and constants as `gripper.py` (`connect`, `status`, `activate`, `move`, `open_`, `close`, `write`, `wait`, `frame`, `crc`, `POS_OPEN`, `POS_CLOSED`, `STA_ACTIVATED`, …) and returns status dictionaries with the same keys. It keeps the gripper's state in memory: it opens no port and does not import `serial`.

It follows the real gripper's status fields:

- `connect()` returns a fresh gripper that is not activated, so every run activates it first.
- `activate` reports gSTA = 1 for one poll, then 3. A move sent before activation is ignored, as on the real gripper.
- A move reports gOBJ = 0 (moving) for at least one poll and `MOVE_TIME` (0.5 s), then its result, so that code polling the gripper sees a realistic delay. Set `fake_gripper.MOVE_TIME = 0` for instant moves. Waits poll every 0.01 s.

The result of a close depends on the scenario, the object between the fingers:

| Object | `obj` | `pos` |
|---|---|---|
| `wide` | 2 (stopped on object) | 120 ± 2 |
| `narrow` | 2 (stopped on object) | 205 ± 2 |
| none | 3 (reached position) | 228 ± 2 |

Opening gives `obj` 3 and `pos` 3 ± 2. The ± 2 is random noise (`NOISE`). `current` is always 0.

> **Placeholders:** the `pos` values for `wide` and `narrow` are not measurements. They are to be replaced once the real blocks exist and have been gripped by the real gripper. The no-object 228 and open 3 are the [observed range](#gripper-serial-link).

Setting the scenario:

| From | Object | Seed |
|---|---|---|
| Code | `set_object('wide' \| 'narrow' \| None)` | `set_seed(n)` |
| Command line | `UR10_SIM_OBJECT=wide\|narrow\|none` (default none) | `UR10_SIM_SEED=<integer>` (default unseeded) |

The same seed gives the same positions, run after run. `set_object_source(fn)` replaces the fixed object with a function called at each close, so that a model of the cell (which slot the arm is at and what it holds) can drive the scenario later.

`set_bench(bench, pose_fn=None)` hands the close and open results to a [simulated bench](#scriptsfake_benchpy) instead. At each move the fake gripper reads the TCP pose and asks the bench what it would feel there; while a block is held, each status poll also lets the bench apply a pending slip, which turns gOBJ to 3. `pose_fn()` returns the TCP pose; by default it is `getActualTCPPose()` from URSim at `127.0.0.1`, connected on first use and disconnected by `s.close()`. Tests pass their own `pose_fn`, so they need no URSim. With a bench set, the bench's seed decides everything and `NOISE` is not added. `set_bench(None)` returns to the fixed object.

```bash
python scripts/fake_gripper.py status                                # fresh gripper, not activated
UR10_SIM_OBJECT=wide UR10_SIM_SEED=1 python scripts/fake_gripper.py close
```

From the command line, `open` and `close` activate the fake gripper first, because each run starts a fresh one.

### `scripts/fake_bench.py`

A simulated bench for simulator runs, because URSim has no blocks. It keeps named slots, each with a grip pose (base frame) and an optional block `{"id", "width_mm"}`, and answers what the gripper would report when it closes or opens at a TCP position. A slot can be a bin: a block released there is gone. The pick-and-place logic sees the blocks only through those gripper readings.

The TCP is at a slot when it is within `TOL` (0.02 m) of the slot's pose; `slot_at(xyz)` returns the nearest such slot, or `None`.

| Action at the TCP | Gripper reports (gOBJ, pos) | Bench |
|---|---|---|
| close at a slot with a block | 2, `pos_for(width_mm)` | block held |
| close at an empty slot or away from any slot | 3, requested position (228 at most) | nothing held |
| TCP leaves the pick slot with a slip pending | 3, 228 | block lost |
| open at an empty slot | 3, requested position (3 at least) | block placed there |
| open at a bin slot | 3, as above | block gone (`binned`) |
| open at an occupied slot or away from any slot | 3, as above | block dropped (`lost`) |

`pos_for` is linear over the 2F-85 stroke: 85 mm at pos 3, 0 mm at pos 228.

> **Unverified:** the width-to-position line. It is to be replaced by measurements of the real blocks in the real gripper.

Faults, set per scenario, all drawn from one generator seeded by the scenario seed, so the same seed repeats the same run:

| Fault | Meaning |
|---|---|
| `p_slip` | Probability that a picked block falls once the TCP leaves the pick slot. The status then changes to gOBJ 3, as the 2F-85 reports a lost object. |
| `p_miss` | Probability that a close at a full slot finds nothing (gOBJ 3); the block stays. |
| `width_noise_mm` | Uniform ± noise added to the block width before converting to pos. |
| `ghost_block` | Probability that a close on nothing reports an object (gOBJ 2, a 30 mm width); nothing is held. |

Every close, open and slip is an event. Events with a `fault` field (`miss`, `slip`, `ghost`) are also kept in `bench.injected`. Given a log path, each event is written as one JSON line, starting with a `start` line that holds the scenario name, the seed, the faults and the initial blocks; every line carries the scenario name and seed.

Scenario file (JSON):

```json
{"name": "nominal", "seed": 1,
 "slots_file": "../scripts/slots.json",
 "slots": {"A": {"block": {"id": "b1", "width_mm": 40}},
           "C": {},
           "bin": {"bin": true}},
 "faults": {"p_slip": 0.1}}
```

Only the slots listed are on the bench. A slot takes its pose from `"pose"` or else from `slots_file` (relative to the scenario file); [`scripts/slots.json`](../scripts/slots.json) holds the taught poses of `A`, `B`, `C`, `bin` and `home`. Unknown fault names, probabilities outside [0, 1], widths outside (0, 85] mm and blocks in a bin are rejected.

```bash
python scripts/fake_bench.py scenarios/nominal.json    # print a scenario
```

| Function | Purpose |
|---|---|
| `load_scenario(path)`, `parse_scenario(data)` | Read and check a scenario. |
| `Bench(scenario, seed=None, log_path=None)` | Bench state for one run; `seed` overrides the scenario's. |
| `close(xyz, target)`, `open(xyz, target)` | Returns `(gOBJ, pos)` and updates the bench. |
| `update(xyz)` | Applies a pending slip; returns the new `(gOBJ, pos)` or `None`. |
| `blocks()`, `binned`, `lost`, `events`, `injected`, `log_info()` | State for checks and logs. |

### Offline tests

The simulation stand-ins have `pytest` tests in [`tests/`](../tests/). They need no robot, no URSim and no gripper: the TCP position is a stand-in value. From the repository root:

```bash
pip install -r requirements.txt
python -m pytest tests -q
```

## Simulation (URSim)

URSim is Universal Robots' offline simulator: the controller and PolyScope, with a simulated arm. It runs on the control computer in Docker and accepts the same `ur_rtde` connections as the robot, so scripts can be tried before they move the real arm.

### Installing Docker

On Pop!_OS (and other Ubuntu-based systems):

```bash
sudo apt install docker.io
sudo usermod -aG docker $USER
```

Then log out and back in, or run `newgrp docker` in the current terminal. Without the group, every Docker command fails with `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`.

### Starting the simulator

```bash
scripts/ursim.sh            # runs in the foreground
docker stop ursim_cb3       # from another terminal, to stop it
```

[`scripts/ursim.sh`](../scripts/ursim.sh) starts the container with these settings:

| Setting | Value |
|---|---|
| Image | `universalrobots/ursim_cb3`, pinned by digest `sha256:ecdab8a2ec1ec795466214f66596b162ae6d21cdc77c3a5c550cf40d753932a4` (pulled as `latest`) |
| Robot model | `ROBOT_MODEL=UR10` |
| Container name | `ursim_cb3`, removed when it stops (`--rm`) |
| Programs folder | host `~/ursim/programs` (created if missing), mounted at `/ursim/programs` |
| Ports | published on `127.0.0.1` only, see below |

| Port | Use |
|---|---|
| 5900 | VNC |
| 6080 | VNC in a browser |
| 29999 | Dashboard Server |
| 30001–30004 | script interfaces and RTDE, used by `ur_rtde` |

The image is not committed. The digest in `ursim.sh` fixes the version. The programs folder stays outside the repository.

**The image simulates a UR5 by default.** `ROBOT_MODEL=UR10` must be set, which `ursim.sh` does. A UR5 has a shorter reach and different link lengths, so poses, inverse kinematics and the distances to the safety planes would not match the robot.

Open the simulated pendant in a browser at <http://localhost:6080/vnc.html?host=localhost&port=6080>. As on the robot, press **ON** on the **Initialization** screen, then **START** to release the brakes. The scripts need the simulated robot in this state, as on the real one.

### Loading the installation

Copy the exported installation from `backups/` into the simulator's programs folder:

```bash
cp backups/miniro_2safety.installation ~/ursim/programs/
```

Load it in the simulated PolyScope from `/ursim/programs` and check that it shows the same values as the robot:

| Check | Expected |
|---|---|
| Safety checksum | `313597321` |
| TCP | `rough_robotiq`, 165.8 mm along tool Z |
| Payload | 1.8 kg |

With this installation loaded, the simulator enforces the same safety configuration as the robot (see [Safety configuration](#safety-configuration)).

### Versions and copying rule

| | PolyScope |
|---|---|
| Robot | 3.15.6 |
| Simulator | 3.15.8 |

- **Files go one way only: robot → simulator.** Never copy an installation or program saved by the simulator (3.15.8) back to the robot (3.15.6).
- **Do not update the robot's PolyScope** to match the simulator.

### Running the scripts against the simulator

Add `--sim` to any script that talks to the robot (see [`scripts/robot.py`](#scriptsrobotpy)). Start with the read-only ones:

```bash
python scripts/show_pose.py --sim --watch
python scripts/safety.py watch --sim
python scripts/pick_test.py --sim       # motion in the simulator; fake gripper
python scripts/pick_place.py --sim
```

The first line of output must read `TARGET: SIMULATOR (127.0.0.1)`. With `--sim` the motion scripts use [`fake_gripper.py`](#scriptsfake_gripperpy): the real gripper is not opened, even if it is plugged in. Set the object for a close with `UR10_SIM_OBJECT`, for example `UR10_SIM_OBJECT=wide python scripts/pick_place.py --sim`.

URSim does not simulate:

- the gripper (it is on RS-485, not on the controller); `fake_gripper.py` stands in for it;
- objects, contact or collisions with the cell;
- the camera.

> **Unverified:** that the simulated controller stops at the same plane margins that `safety.py watch` reports, and that `pick_test.py` and `pick_place.py` behave the same against the simulator as on the robot.

## Shutdown

1. Let scripts finish. They call `stopScript()` to release the robot.
2. Use **Shutdown Robot** on the pendant. Never cut mains power directly.
3. Disconnect the cables from the control computer.
4. Power down before moving the cart.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ping 192.168.0.1` fails | No IPv4 address on the wired interface, or wrong robot IP | Bring the connection up (`nmcli con up ur10`); confirm the IP on the pendant. |
| Error `C207A0 Fieldbus input disconnected` | EtherNet/IP or PROFINET still enabled | Disable both, check MODBUS for unreachable devices, then **Save As** a new installation. |
| RTDE control will not connect | A fieldbus adapter is claiming the RTDE inputs | Same fix as `C207A0`. |
| `gripper.py status` returns `None` | Gripper plug not seated, cart not powered, or USB unplugged | Check the gripper LED (solid red = powered, no communication; blue = communicating). Reseat the gripper plug. Confirm the adapter with `lsusb` (`0403:6015`). |
| `Permission denied` on the serial port | User not in `dialout` | `sudo usermod -aG dialout $USER`, then log out and in. |
| Gripper ignores open/close | Not activated since power-up | `python scripts/gripper.py activate` |
| Fault `0x09` in status | No communication for more than 1 s | Normal at first contact; clears on the next request. |
| Stray replies starting with `0x10` | A second device on the RS-485 line (likely the TeachMate electronics) | Harmless; replies are checked by CRC. |
| `Not moving: path comes within … mm of safety plane …` | The straight-line path passes closer to a plane than `PLANE_MARGIN` (30 mm) | Choose a target or start further from the plane; watch the margins with `safety.py watch` while jogging. |
| `Not moving: path takes … within …° of its limit` | A joint, usually the shoulder (max −51°), gets near its limit along the path | Start from a pose with the shoulder further from −51°, or choose another target. |
| `Not moving: active TCP … is not rough_robotiq` | A different TCP is selected on the pendant | Select `rough_robotiq` in **Installation → TCP Configuration**. Do not change it from code. |
| `safety.py compare` reports differences | The installation on the robot changed, or the wrong file was exported | Confirm the safety checksum on the pendant, then update the constants in `safety.py` and [Safety configuration](#safety-configuration) together. |
| `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock` | User not in the `docker` group | `sudo usermod -aG docker $USER`, then log out and in (or `newgrp docker`). |
| The simulator shows a UR5 | Container started without `ROBOT_MODEL=UR10` | Stop it and start it with `scripts/ursim.sh`, which sets the model. |
| `error: --sim targets the simulator at 127.0.0.1, but --ip is …` (or `UR10_SIM=1 targets …`) | Simulator and a non-local robot IP requested together | Drop `--ip` for the simulator, or drop `--sim` (and `unset UR10_SIM`) for the real robot. |
| `ur_rtde` cannot connect to `127.0.0.1` | Ports 30001–30004 not published, or the simulated robot is not powered on with the brakes released | Start the simulator with `scripts/ursim.sh`; in the simulated PolyScope press **ON**, then **START**. |

> **Warning: unknown USB sticks.** Inspect any unknown USB stick on a computer first, never in the pendant. PolyScope automatically runs `urmagic_*.sh` files from a USB stick as root.

## Reference: Modbus frames

Hex, slave address 9. Checked against `gripper.frame()`.

| Action | Frame |
|---|---|
| Read status | `09 03 07 D0 00 03 04 0E` |
| Reset | `09 10 03 E8 00 03 06 00 00 00 00 00 00 73 30` |
| Activate | `09 10 03 E8 00 03 06 01 00 00 00 00 00 72 E1` |
| Close (full speed and force) | `09 10 03 E8 00 03 06 09 00 00 FF FF FF 42 29` |

Status reply:

```
09 03 06 <status> 00 <fault> <pos request> <pos> <current> <crc>
```

Status byte bits:

| Field | Bits | Meaning |
|---|---|---|
| gACT | 0 | Activation requested |
| gGTO | 3 | Go-to requested |
| gSTA | 4–5 | 3 = activation complete |
| gOBJ | 6–7 | 3 = reached requested position; 2 = stopped on an object while closing |
