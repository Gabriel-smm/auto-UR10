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
- [Shutdown](#shutdown)
- [Troubleshooting](#troubleshooting)
- [Reference: Modbus frames](#reference-modbus-frames)

## Requirements

- Python 3, with the dependencies installed from the repository root:

  ```bash
  pip install -r requirements.txt
  ```

- A computer with an Ethernet port (for the robot) and a free USB port (for the gripper).

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

> **Unverified:** the margins computed by `safety.py` have not yet been compared against the pendant stopping the robot at a plane. Check this with `python scripts/safety.py watch` while jogging slowly toward a plane.

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
```

Example output:

```
TCP pose (base frame)
  X   -123.45 mm    Rx   0.1234 rad    Roll   -179.99°
  Y    456.78 mm    Ry  -3.1234 rad    Pitch    -0.90°
  Z    321.00 mm    Rz   0.0012 rad    Yaw    -175.48°

Joints
  Base        12.34°   Shoulder   -90.00°   Elbow       85.10°
  Wrist 1    -85.00°   Wrist 2    -90.00°   Wrist 3      0.00°
```

| Field | Unit | Notes |
|---|---|---|
| X, Y, Z | mm | TCP position in the base frame. |
| Rx, Ry, Rz | rad | Rotation vector, the representation used by `ur_rtde` and the pendant. |
| Roll, Pitch, Yaw | degrees | Computed from the rotation vector, UR convention R = Rz(yaw)·Ry(pitch)·Rx(roll). |
| Joints | degrees | From `getActualQ()`. |

> **Unverified:** the values have not yet been compared against the pendant's **Move** tab (Base feature) on the hardware. The RPY conversion is checked offline against known rotations only.

### `scripts/pick_place.py`

Moves from the current position to a fixed target pose, closes the gripper, and returns to the start. Run against the robot at `192.168.0.1`:

```bash
python scripts/pick_place.py
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

Both moves are straight lines in Cartesian space, so the path between the start and the target must be clear. To change the target, jog the robot to the new pose, read it with `python scripts/show_pose.py`, and enter it in `TARGET` in metres and radians.

> **Unverified:** not yet run on the hardware.

### `scripts/safety.py`

The cell's safety configuration as constants (see [Safety configuration](#safety-configuration)), plus the checks the motion scripts run before moving. It does not command motion.

```bash
python scripts/safety.py show                                        # print the limits (default)
python scripts/safety.py compare backups/miniro_2safety.installation # check an exported installation
python scripts/safety.py watch                                       # live plane margins and joint headroom
python scripts/safety.py watch --rate 2 --ip 192.168.0.1
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
