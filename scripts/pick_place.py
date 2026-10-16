"""Move to a fixed target pose, close the gripper, return to the start.

Sequence:
    1. Check the gripper answers; activate it if needed.
    2. Record the current TCP pose (the start) and print start and target.
    3. Refuse to move if the start is farther than MAX_DIST from the target
       or the target is outside the safety limits.
    4. Wait for Enter.
    5. Open, move to TARGET, close, move back to the start.

Both moves are straight lines (moveL): make sure the path between the start
and the target is clear. The gripper stays closed at the end. To change the
target, jog the robot there and read the pose with show_pose.py.

Keep a hand on the emergency stop. Do not run a PolyScope program at the
same time: RTDEControlInterface takes over the robot while connected.

Run:
    python pick_place.py
"""

import math

from rtde_control import RTDEControlInterface
from rtde_receive import RTDEReceiveInterface

import gripper as g
from show_pose import format_pose

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROBOT_IP = '192.168.0.1'

# Target TCP pose, base frame: x, y, z (m), rx, ry, rz (rotation vector, rad)
TARGET = [-0.00098, 0.57337, -0.08323, -1.9014, -2.3362, -0.1152]

SPEED = 0.05     # m/s
ACCEL = 0.1      # m/s^2
MAX_DIST = 0.6   # m, refuse to move if the start is farther than this

# ---------------------------------------------------------------------------
# Sequence
# ---------------------------------------------------------------------------


def distance(a, b):
    """Straight-line distance between the positions of two poses (m)."""
    return math.dist(a[:3], b[:3])


def grip(s, pos):
    st = g.move(s, pos)
    label = 'open:  ' if pos == g.POS_OPEN else 'closed:'
    print('gripper', label, st)
    return st


def main():
    s = g.connect()
    try:
        st = g.status(s)
        if st is None:
            raise SystemExit('Gripper not answering: check its plug, cart power and the USB cable')
        if st['sta'] != g.STA_ACTIVATED:
            print('Activating gripper: fingers will open and close fully')
            g.activate(s)

        receive = RTDEReceiveInterface(ROBOT_IP)
        try:
            start = receive.getActualTCPPose()
            q = receive.getActualQ()
            dist = distance(start, TARGET)
            print('Start\n' + format_pose(start, q) + '\n')
            print(f'Target: x {TARGET[0] * 1000:.2f}  y {TARGET[1] * 1000:.2f}  '
                  f'z {TARGET[2] * 1000:.2f} mm   rotvec {TARGET[3]:.4f} {TARGET[4]:.4f} {TARGET[5]:.4f} rad')
            print(f'Distance: {dist * 1000:.1f} mm\n')
            if dist > MAX_DIST:
                raise SystemExit(f'Start is more than {MAX_DIST * 1000:.0f} mm from the target: '
                                 'jog closer first')

            control = RTDEControlInterface(ROBOT_IP)
            try:
                if not control.isPoseWithinSafetyLimits(TARGET):
                    raise SystemExit('Target is outside the safety limits')
                input(f'Press Enter to move at {SPEED} m/s (Ctrl-C to abort) ')

                grip(s, g.POS_OPEN)
                control.moveL(TARGET, SPEED, ACCEL)
                st = grip(s, g.POS_CLOSED)
                if st and st['obj'] == 2:
                    print('Object gripped')
                control.moveL(start, SPEED, ACCEL)

                print('\nEnd\n' + format_pose(receive.getActualTCPPose(), receive.getActualQ()))
            finally:
                control.stopScript()
        finally:
            receive.disconnect()
    finally:
        s.close()


if __name__ == '__main__':
    main()
