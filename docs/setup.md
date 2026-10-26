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
| `--scenario <file>` or `UR10_SIM_SCENARIO=<file>`, with the simulator | simulator | `fake_gripper.py` with a [bench](#scriptsfake_benchpy) for that scenario |

Rejected with an error, before anything connects:

- `--sim` or `UR10_SIM=1` with any other `--ip`, for example `--sim --ip 192.168.0.1`;
- `UR10_SIM` set to anything other than `1`, `0` or empty;
- a scenario without the simulator, for example `--scenario scenarios/nominal.json` alone.

Before connecting, it prints `TARGET: SIMULATOR (127.0.0.1)` or `TARGET: REAL ROBOT (192.168.0.1)`. Check this line before every motion run, especially when `UR10_SIM` may be set in the shell.

With a scenario, it also prints `SCENARIO: <name>  seed <n>  log logs/<name>-<YYYYmmdd-HHMMSS>.jsonl`. `UR10_SIM_SEED=<n>` overrides the scenario's seed. The log holds the bench's events: a `start` line with the scenario name, seed, faults, slip signal and initial blocks, then one line per close, open and slip, with any injected fault. `logs/` is not committed.

| Function | Purpose |
|---|---|
| `add_args(parser)` | Add `--sim`, `--ip` and `--scenario` to an `argparse` parser. |
| `select(parser, args)` | Apply the rules above, print the target, and return `(ip, sim)`. |
| `gripper(sim, args=None, pose_fn=None)` | The gripper module for the target: `fake_gripper` or `gripper`. With a scenario in `args`, it gives the fake gripper a bench and opens the log; `pose_fn()` is where the bench reads the TCP pose (default: URSim). |

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

Opening gives `obj` 3 and `pos` 3 ± 2. The ± 2 is random noise (`NOISE`). `current` is 0, except while holding an object after a close with force above 0, when it is 5 (`HOLD_CURRENT`, the value read on the real gripper at force 100).

> **Placeholders:** the `pos` values for `wide` and `narrow` are not measurements. They are to be replaced once the real blocks exist and have been gripped by the real gripper. The no-object 228 and open 3 are the [observed range](#gripper-serial-link).

Setting the scenario:

| From | Object | Seed |
|---|---|---|
| Code | `set_object('wide' \| 'narrow' \| None)` | `set_seed(n)` |
| Command line | `UR10_SIM_OBJECT=wide\|narrow\|none` (default none) | `UR10_SIM_SEED=<integer>` (default unseeded) |

The same seed gives the same positions, run after run. `set_object_source(fn)` replaces the fixed object with a function called at each close, so that a model of the cell (which slot the arm is at and what it holds) can drive the scenario later.

`set_bench(bench, pose_fn=None)` hands the close and open results to a [simulated bench](#scriptsfake_benchpy) instead. At each move the fake gripper reads the TCP pose and asks the bench what it would feel there; while a block is held, each status poll also lets the bench apply a pending slip, which may change the status (see `slip_signal`). The force of a close is passed to the bench, which uses it to decide. `pose_fn()` returns the TCP pose; by default it is `getActualTCPPose()` from URSim at `127.0.0.1`, connected on first use and disconnected by `s.close()`. Tests pass their own `pose_fn`, so they need no URSim. With a bench set, the bench's seed decides everything and `NOISE` is not added. `set_bench(None)` returns to the fixed object.

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
| TCP leaves the pick slot with a slip pending | unchanged after a close at force 0; 3, 228 after a close with force (see `slip_signal`) | block lost |
| open at an empty slot | 3, requested position (3 at least) | block placed there |
| open at a bin slot | 3, as above | block gone (`binned`) |
| open at an occupied slot or away from any slot | 3, as above | block dropped (`lost`) |

`pos_for` comes from [`scripts/grip_width.py`](../scripts/grip_width.py), which interpolates linearly between the points in its `CALIBRATION`; `width_for(pos)` is the inverse, used by the [skills](#scriptsskillspy) to report `width_mm`:

| Width | pos | Source |
|---|---|---|
| 0 mm | 228 | assumed: closed on nothing (the observed no-object stop) |
| 73 mm | 67 | measured on the 2F-85, `python gripper.py close` at force 0 and at force 100, 2026-10-20 |
| 85 mm | 3 | assumed: fully open (the observed open stop) |

A straight line from 85 mm at pos 3 to 0 mm at pos 228 would put 73 mm at pos 35, not the measured 67, so the relation is not linear over the stroke. Between the points the values are interpolations.

> **Unverified:** every width other than 73 mm. Add a point to `CALIBRATION` for each real block measured.

Faults, set per scenario, all drawn from one generator seeded by the scenario seed, so the same seed repeats the same run:

| Fault | Meaning |
|---|---|
| `p_slip` | Probability that a picked block falls once the TCP leaves the pick slot. The slip also happens at the next open if no status poll applied it on the way; released at the pick slot itself, the block is put back instead. |
| `p_miss` | Probability that a close at a full slot finds nothing (gOBJ 3); the block stays. |
| `width_noise_mm` | Uniform ± noise added to the block width before converting to pos. |
| `ghost_block` | Probability that a close on nothing reports an object (gOBJ 2, a 30 mm width); nothing is held. |

`slip_signal` (top-level scenario key) sets what a slip does to the status:

| `slip_signal` | Status after the block falls |
|---|---|
| `auto` (default) | As measured on the 2F-85: unchanged if the block was gripped at force 0; gOBJ 3, pos 228 if it was gripped with force above 0. |
| `silent` | Always unchanged: gOBJ 2 and the pos of the block. The loss shows only at the next close or place. |
| `status` | Always gOBJ 3, pos 228. |

`auto` follows two tests on the real gripper (2026-10-20), each closing on a 73 mm object, pulling it out by hand, then reading `python gripper.py status`:

| Force | After the close | After the object was pulled out |
|---|---|---|
| 0 | gOBJ 2, pos 67, current 0 | gOBJ 2, pos 67: no change |
| 100 | gOBJ 2, pos 67, current 5 | gOBJ 3, pos 228: the fingers closed fully |

At force 0 the gripper keeps no holding current and cannot sense the loss; at force 100 it holds and closes on when the object leaves. The stop position was the same at both forces.

> **Unverified:** forces other than 0 and 100. `auto` treats every force above 0 like 100.

Every close, open and slip is an event. Events with a `fault` field (`miss`, `slip`, `ghost`) are also kept in `bench.injected`. Given a log path, each event is written as one JSON line, starting with a `start` line that holds the scenario name, the seed, the faults and the initial blocks; every line carries the scenario name and seed.

Scenario file (JSON):

```json
{"name": "nominal", "seed": 1,
 "instruction": "Move the block in A to C.",
 "expected": {"slots": {"A": null, "C": "b1"}, "binned": []},
 "slots_file": "../scripts/slots.json",
 "slots": {"A": {"block": {"id": "b1", "width_mm": 40}},
           "C": {},
           "bin": {"bin": true}},
 "faults": {"p_slip": 0.1},
 "slip_signal": "auto"}
```

An optional `"description"` is ignored by the code. `"instruction"` is the task given to the decider by [`run_task.py`](#scriptsrun_taskpy), and `"expected"` is the bench at the end of a successful episode: the block id (or `null`) per slot, and the ids that should be in the bin. The fault scenarios use one of two instructions, the ones [`decision_rules.py`](#scriptsdecision_rulespy) understands: "Put every block on the bench in the bin." or "Move the block in X to Y." (`nominal`, `single_A`, `single_B`, `single_C`). The `novel_*` scenarios have no faults and instructions the rules cannot carry out (no rule, or a regex that misreads them); they measure whether a decider follows an instruction written in free text. Only the slots listed are on the bench. A slot takes its pose from `"pose"` or else from `slots_file` (relative to the scenario file); [`scripts/slots.json`](../scripts/slots.json) holds the taught poses of `A`, `B`, `C`, `bin` and `home`, and `approach_z`, the height (m, base frame) above a slot from which the [skills](#scriptsskillspy) descend (`default` 0.10, or per slot name). Unknown fault names, probabilities outside [0, 1], widths outside (0, 85] mm and blocks in a bin are rejected.

```bash
python scripts/fake_bench.py scenarios/nominal.json    # print a scenario
```

The scenarios in [`scenarios/`](../scenarios/) all use slots `A`, `B`, `C` and `bin` from `slots.json`. The block widths (15 to 60 mm) are placeholders until the real blocks exist.

| Scenario | Seed | Bench | Faults |
|---|---|---|---|
| `empty_bench` | 1 | Nothing on the bench: every close reports gOBJ 3. | none |
| `full_bench` | 1 | Every slot holds a block; a place needs the bin or a freed slot. | none |
| `ghost_always` | 1 | Empty bench, but every close on nothing reports an object. | `ghost_block` 1 |
| `ghost_sometimes` | 1 | 30 % of closes on nothing report an object. | `ghost_block` 0.3 |
| `miss_always` | 1 | Every close at a full slot finds nothing. | `p_miss` 1 |
| `miss_sometimes` | 1 | 30 % of closes at a full slot miss. | `p_miss` 0.3 |
| `mixed_faults_seed1` | 1 | All faults at once. | `p_slip` 0.2, `p_miss` 0.2, `width_noise_mm` 2, `ghost_block` 0.2 |
| `mixed_faults_seed2` | 2 | As mixed_faults_seed1, other seed. | `p_slip` 0.2, `p_miss` 0.2, `width_noise_mm` 2, `ghost_block` 0.2 |
| `mixed_faults_seed3` | 3 | As mixed_faults_seed1, other seed. | `p_slip` 0.2, `p_miss` 0.2, `width_noise_mm` 2, `ghost_block` 0.2 |
| `narrow_only` | 1 | Two 15 mm blocks. | none |
| `novel_clear_B` | 1 | "Clear slot B: put its block in the bin." Blocks at A and B. | none |
| `novel_except_A` | 1 | "Put every block in the bin except the one in A." Blocks at A, B, C. | none |
| `novel_paraphrase` | 1 | "Take the block that is at C and leave it at A." | none |
| `novel_two_moves` | 1 | "Move the block in A to C, then the block in B to A." | none |
| `novel_wide_to_bin` | 1 | "Put every block wider than 35 mm in the bin; put the other blocks back where they were." 20, 40 and 30 mm blocks; the width is known only once a block is gripped. | none |
| `nominal` | 1 | A wide block at A, a narrow one at B, C empty, no faults. | none |
| `similar_widths` | 1 | 30 and 32 mm blocks with 2 mm noise: the widths overlap. | `width_noise_mm` 2 |
| `single_A` | 1 | One wide block at A. | none |
| `single_B` | 1 | One wide block at B. | none |
| `single_C` | 1 | One wide block at C. | none |
| `slip_always` | 1 | Every picked block falls once the TCP leaves the slot. | `p_slip` 1 |
| `slip_always_status` | 1 | As slip_always, but the status turns to gOBJ 3 when the block falls (not what the 2F-85 does at force 0). | `p_slip` 1, `slip_signal` status |
| `slip_sometimes` | 1 | 30 % of picked blocks fall in transport. | `p_slip` 0.3 |
| `wide_only` | 1 | Two 60 mm blocks. | none |
| `width_noise_large` | 1 | Nominal bench with 5 mm width noise. | `width_noise_mm` 5 |
| `width_noise_small` | 1 | Nominal bench with 1 mm width noise. | `width_noise_mm` 1 |

| Function | Purpose |
|---|---|
| `load_scenario(path)`, `parse_scenario(data)` | Read and check a scenario. |
| `Bench(scenario, seed=None, log_path=None)` | Bench state for one run; `seed` overrides the scenario's. |
| `close(xyz, target)`, `open(xyz, target)` | Returns `(gOBJ, pos)` and updates the bench. |
| `update(xyz)` | Applies a pending slip; returns the new `(gOBJ, pos)` with `slip_signal` `status`, else `None`. |
| `blocks()`, `binned`, `lost`, `events`, `injected`, `log_info()` | State for checks and logs. |

### `scripts/skills.py`

The actions a decider can choose, each planned and checked before anything moves. It is a module, not a command; [`run_task.py`](#scriptsrun_taskpy) uses it.

The decider chooses among **primitives**, one motion or one gripper action per step:

| Option | Segments | Gripper |
|---|---|---|
| `move:A`, `move:B`, `move:C`, `move:bin` | lift (if below the target's approach height), transit to the approach point above the slot; it stops there | — |
| `down` | from above the slot the TCP is over, straight down to its grip pose | — |
| `up` | from a slot, straight up to its approach point | — |
| `close` | none | close (force 100) |
| `open` | none | open |
| `home` | lift, transit to `home` | — |

`down` and `up` are refused when the TCP is not over a slot (within 20 mm horizontally): the plan has no segments, `ok` is false and the reason is `the gripper is not above a slot`, so nothing moves. `where(poses, approach, tcp)` gives the slot and level (`down` within 10 mm of the grip pose, `above` between it and the approach height).

Moving one block takes about eight primitives: `move:A`, `down`, `close`, `up`, `move:C`, `down`, `open`, `up`. The macros `pick(slot)` (move above, descend, close, lift back), `place(slot)` and `open_gripper()` remain as functions for scripts and tests but are not offered to deciders.

The approach point is the slot pose raised by `approach_z` from [`slots.json`](../scripts/slots.json) (0.10 m) along the base Z axis. Segments of zero length are skipped.

> **No guard on the options.** Every primitive is offered at every step, to see how a decider behaves. The safety checks (planes, joint limits, TCP, speed) still refuse unsafe paths, but nothing stops a `down` with the gripper closed into a slot that holds a block, or a `down` while holding a block into an occupied slot. In the simulator that only shows up in the bench log; on the real arm it would push the fingers or a block into a block. On the real robot, the operator's confirmation of each step is the only guard against it.

| Motion | Used for | Speed | Checked with |
|---|---|---|---|
| `moveL` (straight line) | lift, descend, retreat | 0.1 m/s, 0.15 m/s² | `safety.preflight`: active TCP, speed, plane margins and joint headroom along the line |
| `moveJ` (joint interpolation) | transit | 0.25 rad/s, 0.5 rad/s² | `check_movej`: active TCP; joint headroom at both ends (each joint moves linearly, so the ends are its extremes); plane margins at 50 poses along the move, from the controller's forward kinematics |

Transits are joint moves because a straight line between distant poses can take the shoulder past its narrowed limit (−51°): in URSim, the line from above slot C to `home` reached −34°. The joint targets come from the controller's inverse kinematics, chained from the current joint angles.

`plan(cell, skill, arg)` returns the segments (`kind`, `motion`, `from`, `to`, `q_to`), the gripper action, the speeds and force, and one preflight entry per segment (`problems` and the printed `report`). `ok` is false if any segment has a problem; `execute` then moves nothing and returns the reason. `execute` also refuses a plan if the arm has moved more than 5 mm since it was made.

The result holds only values read at the end of the skill:

```json
{"skill": "pick", "args": "A", "ok": true, "reason": null,
 "gripper": {"obj": 2, "pos": 140, "width_mm": 39.9},
 "tcp": [0.26359, 0.35385, 0.03192, 2.3187, 2.0941, 0.0978], "duration_s": 6.7}
```

`width_mm` is `grip_width.width_for(pos)` when gOBJ is 2 (stopped on an object), else `null`. Skills make no decisions: no retries, no choice of the next skill.

Moves are asynchronous. Setting the abort event, or Ctrl-C, calls `stopL` or `stopJ` (2.0 m/s² or rad/s²) and returns `ok` false, reason `aborted`; the arm stays where it stopped.

[`scripts/fake_arm.py`](../scripts/fake_arm.py) stands in for `RTDEControlInterface` and `RTDEReceiveInterface` in the offline tests and with `run_task.py --backend fake`: moves end at once (or after a set time), the active TCP is the expected one, and its kinematics keep every joint far from its limits, so the plane checks run as against the robot.

> **Unverified on the real robot:** every skill. Tested in URSim (pick, place, home, abort during a moveJ) and offline.

### `scripts/state.py`

Builds the state a decider sees, from real readings only: no LLM builds or edits it, and it never holds the bench's true contents or the injected faults. `Tracker(instruction, poses, approach)` keeps the episode's skill results; `build(gripper, tcp)` returns:

```json
{"step": 1, "instruction": "Move the block in A to C.",
 "gripper": {"obj": 2, "meaning": "stopped on an object", "pos": 140, "width_mm": 39.9},
 "holding": true, "tcp_at": "A",
 "slots": {"A": {"picks": 1, "gripped": 1, "empty": 0, "placed": 0, "event": "taken",
                 "last": "pick A: gripper stopped on an object, width 39.9 mm"},
           "B": {"picks": 0, "gripped": 0, "empty": 0, "placed": 0, "event": null, "last": null},
           "...": "..."},
 "history": [{"step": 0, "skill": "pick", "args": "A", "ok": true, "reason": null,
              "gripper": {"obj": 2, "pos": 140, "width_mm": 39.9}, "tcp_at": "A", "duration_s": 6.7}]}
```

| Field | From |
|---|---|
| `gripper`, `holding` | the gripper status read now; `holding` is gOBJ 2 |
| `tcp_at` | the slot the TCP is at or above (up to its approach height), `home`, or `null` |
| `slots` | per slot, counted from skill results: picks, picks that ended holding (`gripped`) or on nothing (`empty`), places, the latest `event` there (`taken`, `empty`, `released`, `failed`, or `null` if never visited), `width_mm` of the block taken from or left there (as measured when it was gripped), and the last result in words |
| `history` | the last 5 skill results |

`options(state)` gives the same list at every step, from the skill library and `slots.json` only: `move:A`, `move:B`, `move:C`, `move:bin`, `down`, `up`, `open`, `close`, `home`, `done`. The state's `tcp_at` and `tcp_level` (`above`, `down`, or `null`) say where the arm is. Slot events come from the primitives: a `close` while down at a slot is a pick (`taken` or `empty`); an `open` while down at a slot, or anywhere over the bin, after holding a block, is a place (`released`). The macros `pick` and `place` are still recorded the old way.

### `scripts/decision_rules.py`

The hand-written baseline decider, for comparison with the model. It reads only the state and understands the two scenario instructions:

It first picks a goal:

| Instruction | Goal |
|---|---|
| Put every block on the bench in the bin. | holding: `place:bin`; else `pick` the first slot not yet gripped from and not found empty twice; none left: `done` |
| Move the block in X to Y. | holding: `place:Y`; gripped from X and released at Y: `done`; X found empty fewer than twice: `pick:X`; else `done` |

then takes the first primitive towards it (`decision.next_primitives`, shared with `summarize.py`):

| Goal | Primitives, from where the arm and gripper are |
|---|---|
| `pick:X` | `open` if the gripper is closed and empty; `up` if down in another slot; `move:X`; `down`; `close` |
| `place:Y` | `up` if down in another slot; `move:Y`; `down`; `open` (over the bin it opens from above) |

Its probabilities are 1.0 for the choice and 0.0 for the rest. `last_ok` is judged from the last result: a close that ended holding, an open that ended open, and a move after which a held block is gone (a slip) is a failure. `task_done` is 1.0 when it chooses `done`. Every decider implements `decide(state, options) -> Decision` ([`scripts/decision.py`](../scripts/decision.py)): `choice`, `probs`, `last_ok_prob`, `task_done_prob`, `latency_s`, `raw`.

With the fault-free scenarios, ghost blocks and occasional misses, the rules reach the expected bench. They cannot recover a block that slipped (it is lost) or get past a slot that always misses.

### `scripts/decision_model.py`

Decider backed by a vllm-sr decision model, which answers typed questions with probabilities and generates no text. The default is [`vllm-sr/d3-lite`](https://huggingface.co/vllm-sr/d3-lite); [`vllm-sr/Decision-2.0-Sol-2B`](https://huggingface.co/vllm-sr/Decision-2.0-Sol-2B) has the same interface. Install the dependencies first:

```bash
pip install -r requirements-model.txt    # torch, transformers>=5.17, accelerate, safetensors,
                                         # pillow, torchvision, opencv-python-headless (d3 imports them)
```

| Model | Parameters | On the control laptop (RTX 500 Ada, 4 GB) |
|---|---|---|
| `vllm-sr/d3-lite` (default) | 0.85 B | GPU: 1.6 GB loaded, 1.8 GB peak; about 0.5 s per decision (3 s for the first) |
| `vllm-sr/Decision-2.0-Sol-2B` | 1.88 B | does not fit the GPU; CPU: about 9 GB of RAM, 30 to 55 s per decision |

Each step makes one `model.system_one(state=json.dumps(view(state)), questions=...)` call. The model does not see the full state but `view(state)`, a short summary of what is known about each slot:

```json
{"instruction": "Move the block in A to C.", "gripper": "open, empty", "arm": "above C",
 "blocks_removed_from": ["A"], "blocks_put_in": ["C"], "blocks_in_bin": 0,
 "found_empty": [], "not_visited_yet": ["B"]}
```

| Field | From |
|---|---|
| `gripper` | `holding a block, <width> mm wide` (gOBJ 2); `open, empty` or `closed, empty` (gOBJ 3, pos below or above 128); otherwise the status meaning |
| `blocks_removed_from`, `blocks_put_in`, `found_empty` | slots (not the bin) whose latest `event` is `taken`, `released`, `empty` |
| `arm` | `above X`, `lowered into X` (not "down", which is an option word), `at home`, or `elsewhere, not over a slot` |
| `blocks_in_bin` | places into the bin |
| `not_visited_yet` | slots (not the bin) with no event yet, or whose last skill failed |

The model leans towards options whose words the state repeats. With the full state, the `pick` / `A` in `history` and `slots.A.last` pulled it back to A: after `pick:A` it chose `place:A`, and in `slip_always` it kept choosing `pick:A`. The view therefore has no action history, no skill names and no status codes, and a slot appears at most once. Adding the last action back made the choices worse. The rules decider, the panel and the log keep the full state; the view is logged in the decision's `extra.model_state`.

Measured on d3-lite (GPU), on 8 states from the `nominal`, `full_bench` and `empty_bench` scenarios, plus 2 from `slip_always` for the final view; choice correct:

| Input | Correct | Example |
|---|---|---|
| full state (before) | 4/8 | after `pick:A`: `place:A` 0.86; after `place:C`: `pick:A` 0.79 |
| view with an action history | 6/8 | after `place:C`: `pick:C` 0.73 |
| `view(state)` | 10/10 | after `pick:A`: `place:C` 0.66; after `place:C`: `done` 0.51; `slip_always` after `pick:A`: `pick:C` |

The choice is right but its probability is often 0.3 to 0.66, below the default `--threshold` of 0.7, so in auto mode those steps abstain. `last_ok` is close to 0 in every case (also with the full state and with the last action in the view): d3-lite's `last_ok` does not detect failed skills, and the `detected` column of `summarize.py` should be read with that in mind.

| Question | Type | Asked |
|---|---|---|
| `next_skill` | `choice` | Given where the blocks are now and what the instruction asks, which action comes next? The criteria are the valid options, each with a short description (`decision.describe`), e.g. `pick:A`: "Take the block that is in A into the empty gripper. Only useful while a block is still believed to be in A."; `done`: "Stop: the instruction is fully carried out, or every slot has been checked and nothing is left to do." |
| `last_ok` | `noul` (yes/no) | Did the most recent action do what it was meant to (for example, the gripper closed on a block when taking one)? |
| `task_done` | `noul` | Do the blocks' current positions already satisfy the instruction? |

> **Unverified:** the view has been checked offline against the fake bench only, not yet in a full `run_task.py --sim` episode or on the robot.

**With the primitives** (fake backend, threshold 0, 30 steps), d3-lite does not get past the first move: in `nominal` it chooses `move:A` (0.90) and then `move:A` again at 0.75 for every remaining step, although the view says `arm: above A`; in `single_B` it repeats `move:B` (0.82); in `full_bench` it repeats `move:bin` (0.37). The table above was measured with the macros (`pick`, `place`).

A real answer to the old full-state input (d3-lite, scenario `nominal`, after `pick:A`), kept as a parsing fixture:

```json
{"answers": {"next_skill": {"choice": "place:A", "confidence": 0.489, "type": "choice",
                            "probabilities": {"place:A": 0.521, "place:C": 0.431, "done": 0.018,
                                              "place:bin": 0.013, "home": 0.011, "place:B": 0.007}},
             "last_ok": {"noul": 0.105, "type": "noul"},
             "task_done": {"noul": 0.196, "type": "noul"}},
 "model": "d3-lite", "usage": {"input_tokens": 1341, "output_tokens": 0}}
```

The decision's `choice` is the offered option with the highest probability, `probs` are the `next_skill` probabilities, and `last_ok_prob` and `task_done_prob` are the `noul` values. The model's own `confidence` is kept in `extra` and in the log; it is not the probability the threshold is compared with. An answer without probabilities (for example an over-long state) gives all zeros, so the step abstains.

| Option | Values | Notes |
|---|---|---|
| `--model` | default `vllm-sr/d3-lite` | loaded with `AutoModel.from_pretrained(..., trust_remote_code=True)` |
| `--device` | `auto` (GPU if any), `cuda`, `cpu` | the model's runtime fixes the numerics: BF16 autocast on a GPU, FP32 on the CPU |
| `--bf16-resident` | flag | keeps the weights in BF16 (Decision 2.0 only; d3 refuses it) |

Sol-2B does not fit the 4 GB GPU: loading runs out of memory at about 3.6 GB, with or without `--bf16-resident`. Both runtimes refuse a `quantization_config`, so 8-bit or 4-bit loading through bitsandbytes is not possible, and the published quantized Sol-2B versions (GGUF, ONNX, MLX) are for other runtimes. That is why the default is d3-lite. A `CUDA out of memory` while loading stops with a message to use a smaller model or `--device cpu`. Both models run their own code from the Hugging Face repository (`trust_remote_code`); review it before loading a new model or revision.

Tests: `tests/test_deciders.py` parses saved real answers (`tests/fixtures/d3lite_after_pick.json`, `sol2b_after_pick.json`); `python -m pytest tests -m model` also loads the default model (on the GPU if there is one; `UR10_MODEL_DEVICE=cpu` to force the CPU).

### `scripts/run_task.py`

Runs one episode: a decider chooses skills until it says `done`. Each step: build the state ([`state.py`](#scriptsstatepy)) → decide → abstain if the chosen option's probability is below `--threshold` → plan and preflight the skill ([`skills.py`](#scriptsskillspy)) → show it → confirm → execute → log.

```bash
python scripts/run_task.py --sim --scenario scenarios/nominal.json --decider rules        # step mode
python scripts/run_task.py --sim --scenario scenarios/nominal.json --decider model     # d3-lite
python scripts/run_task.py --sim --backend fake --scenario scenarios/full_bench.json --mode headless
python scripts/run_task.py --instruction "Move the block in A to C."                     # real robot
```

| Option | Default | Notes |
|---|---|---|
| `--sim`, `--ip`, `--scenario` | real robot | as for every robot script ([`robot.py`](#scriptsrobotpy)); the simulator needs `--scenario` |
| `--backend` | `ursim` | `fake`: [`fake_arm.py`](../scripts/fake_arm.py) instead of URSim, instant moves (simulator only) |
| `--decider` | `rules` | `rules` ([`decision_rules.py`](#scriptsdecision_rulespy)) or `model` ([`decision_model.py`](#scriptsdecision_modelpy)) |
| `--model`, `--device`, `--bf16-resident` | `vllm-sr/d3-lite`, `auto` | model decider only |
| `--instruction` | the scenario's | required on the real robot |
| `--mode` | `step` | `step`: confirm every skill; `auto` and `headless` (no panel, log only): simulator only |
| `--threshold` | 0.7 | below it the step abstains: step mode asks you, auto and headless end the episode as `abstained` |
| `--max-steps` | 60 | one moved block takes about 8 primitive steps |
| `--speed` | 0.1 m/s | moveL speed; at most 0.1 on the real robot |
| `--seed` | the scenario's | bench seed |

**Panel**, one per step: the TARGET line (red background on the real robot), scenario, seed, decider, step k/max; the state sent to the decider (summary, `s` expands it); every option with its probability bar, the choice (▶), an override (O), the threshold, `last_ok`, `task_done`, latency and VRAM; the plan with each segment's motion, target and preflight result, before anything moves; after the move, the measured gripper reading, TCP, ok/reason and duration; in the simulator only, the bench truth (slots, held, binned, lost, faults injected in this step), marked as never shown to the decider.

**Keys** (step mode):

| Key | Action |
|---|---|
| Enter | execute the shown choice (or the override) |
| `o`, then a number | override: execute another valid option instead; the plan is redrawn and Enter is needed again |
| `k` | skip this step without moving |
| `p` | pause / resume |
| `s` | expand / collapse the state |
| `a` | abort: stop the move (`stopL`/`stopJ`) where it is; the arm does not go home |
| Ctrl-C | the same as `a`, at any time |

In `auto`, `p` and `a` work between steps and `a` and Ctrl-C during a move.

**Real robot**: only `--mode step`; `--instruction` is required; `--speed` at most 0.1 m/s. Before anything connects it shows a checklist (emergency stop in reach, area clear, reduced speed, no PolyScope program running) and continues only if you type `ok`. An unactivated gripper is activated only after Enter. At `done` it asks whether the instruction was carried out (`y`/`n`), since there is no bench truth.

**Log**: `logs/<YYYYmmdd-HHMMSS>-<scenario or real>-<decider>.jsonl`.

| Line | Fields |
|---|---|
| `start` | `run_id`, `target`, `ip`, `backend`, `scenario`, `seed`, `faults`, `instruction`, `expected`, `decider`, `model`, `device`, `threshold`, `mode`, `max_steps`, `speed`, `git_commit`, `bench_log` |
| `step` | `step`, `state`, `options`, `questions`, `decision` (`choice`, `probs`, `last_ok_prob`, `task_done_prob`, `latency_s`, `raw`, `extra`), `abstained`, `operator` (`action`: `exec`, `override`, `skip`, `abort`, `auto` or `abstain`; `choice`: the override), `executed`, `plan`, `preflight`, `result`, `vram_peak_mb`; simulator only: `bench`, `injected` |
| `end` | `outcome` (`success`, `fail`, `abstained`, `aborted`, `max_steps`, `error`), `steps`; simulator: `final_bench`, `expected`, `match`; real robot: `operator_verdict` |

`decision.choice` is always the decider's choice; what ran is in `executed`, and an override is in `operator`, so overrides are never mixed with the decider's choices. In the simulator, `success` means the bench matches the scenario's `expected` when the episode ends with `done`.

> **Unverified on the real robot.** Tested in URSim (rules decider, `full_bench` to success in 7 steps; abort with `a` and with Ctrl-C during a moveJ) and on the fake backend.

### `scripts/replay.py`

Shows a logged episode again, step by step, in the same panels as `run_task.py`, with the operator's action under each decision. No robot or simulator is needed.

```bash
python scripts/replay.py logs/20261020-202116-full_bench-rules.jsonl     # Enter: next step, q: quit
python scripts/replay.py LOG --all                                        # every step at once
```

### `scripts/run_suite.py`

Runs every scenario under several seeds, headless in the simulator, loading the decider (and the model) once. Each episode writes its own log (and the bench's event log under `bench/`); the list goes to `logs/suite-<YYYYmmdd-HHMMSS>.json`.

```bash
python scripts/run_suite.py --decider rules --seeds 1 2 3
python scripts/run_suite.py --decider model --seeds 1 2 3                        # d3-lite on the GPU
python scripts/run_suite.py --decider rules --backend ursim          # through URSim: real motion times
```

| Option | Default |
|---|---|
| `--decider`, `--model`, `--device`, `--bf16-resident` | `rules` |
| `--seeds` | 1 2 3 |
| `--backend` | `fake` (instant moves); `ursim` for URSim |
| `--scenarios` | `scenarios/*.json` |
| `--threshold`, `--max-steps`, `--log-dir` | 0.7, 20, `logs/` |

With the fake backend the rules suite (21 scenarios × 3 seeds) takes about 15 s. With d3-lite on the GPU each decision takes about 0.5 s; with Sol-2B on the CPU, 30 to 55 s, so a full Sol-2B suite takes hours.

### `scripts/summarize.py`

Tables per decider and model from suite files, log folders or single logs:

```bash
python scripts/summarize.py logs/suite-20261020-202636.json
python scripts/summarize.py logs/suite-A.json logs/suite-B.json      # rules and model side by side
```

| Column | Meaning |
|---|---|
| success, outcomes | episodes ending in each outcome |
| step accuracy | decisions judged right against the bench truth before the step (below) |
| abstentions right / wrong / unscored | an abstention is right when the decider's choice would have been wrong |
| mean steps; latency median / p95; VRAM peak | per episode; per decision; the highest `vram_peak_mb` logged |
| per fault: detected | the next decision's `last_ok` was below 0.5 |
| per fault: retried same slot | one of the next two executed skills picked the faulted slot again |
| per fault: wrong done | the episode ended with `done` and the bench did not match `expected` |

A decision is right if an ideal decider would take it, given the bench truth: place the held block where `expected` wants it; with nothing held, pick a block that is not yet in place, or `done` if every block is. What the decider cannot know also counts as right: picking a slot never gripped from and found empty fewer than twice, and placing when the state says holding but nothing is (a ghost block). Steps where no offered option is right are not scored.

The rules decider over the 63 fault-free and faulty episodes (fake backend, seeds 1–3): 42 successes, 99% step accuracy. The 21 failures are the scenarios it cannot recover from: slips (the block is lost), `miss_always`, and some ghost and miss cases.

### Offline tests

The simulation stand-ins have `pytest` tests in [`tests/`](../tests/). They need no robot, no URSim and no gripper: the TCP position is a stand-in value. From the repository root:

```bash
pip install -r requirements.txt
python -m pytest tests -q                # everything except the real model
python -m pytest tests -q -m model       # the real Decision model too (needs requirements-model.txt)
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

The first line of output must read `TARGET: SIMULATOR (127.0.0.1)`. With `--sim` the motion scripts use [`fake_gripper.py`](#scriptsfake_gripperpy): the real gripper is not opened, even if it is plugged in. Set the object for a close with `UR10_SIM_OBJECT`, for example `UR10_SIM_OBJECT=wide python scripts/pick_place.py --sim`, or give a [bench scenario](#scriptsfake_benchpy) so that the result depends on where the TCP is:

```bash
python scripts/pick_place.py --sim --scenario scenarios/nominal.json
```

With `nominal.json`, a close at slot `A` reports gOBJ 2 and pos 140 (a 40 mm block); a close away from every slot reports gOBJ 3.

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
