"""Arm + gripper smoke test for the UR10 and Robotiq 2F-85.

Sequence:
    1. Check the gripper answers; activate it if needed.
    2. Record the current TCP pose; refuse to move if the lift fails the
       checks in safety.py (active TCP, speed, plane and joint-limit margins).
    3. Open, lift the TCP 2 cm, close, open.
    4. Return to the start pose.

Keep a hand on the emergency stop. Do not run a PolyScope program at the
same time: RTDEControlInterface takes over the robot while connected.

Run:
    python pick_test.py
"""

from rtde_control import RTDEControlInterface
from rtde_receive import RTDEReceiveInterface

import gripper as g
import safety

ROBOT_IP = '192.168.0.1'

LIFT = 0.02    # m, upward offset along base Z
SPEED = 0.05   # m/s
ACCEL = 0.1    # m/s^2


def grip(s, pos):
    st = g.move(s, pos)
    label = 'open:  ' if pos == g.POS_OPEN else 'closed:'
    print('gripper', label, st)


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
        control = RTDEControlInterface(ROBOT_IP)
        try:
            start = receive.getActualTCPPose()
            up = list(start)
            up[2] += LIFT
            print('TCP start:', start)

            problems = safety.preflight(control, start, up, receive.getActualQ(), SPEED)
            if problems:
                raise SystemExit('Not moving:\n  ' + '\n  '.join(problems))

            grip(s, g.POS_OPEN)
            control.moveL(up, SPEED, ACCEL)
            grip(s, g.POS_CLOSED)
            grip(s, g.POS_OPEN)
            control.moveL(start, SPEED, ACCEL)

            print('TCP end:  ', receive.getActualTCPPose())
        finally:
            control.stopScript()
    finally:
        s.close()


if __name__ == '__main__':
    main()
