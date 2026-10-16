"""Print the UR10's current position: TCP pose and joint angles.

Read-only: uses RTDEReceiveInterface only, so it does not take over the
robot and can run while jogging in Freedrive or the Move tab.

The TCP pose is given in the base frame, in mm and as a rotation vector
(as on the pendant's Move tab), plus roll/pitch/yaw in degrees.

Command line:
    python show_pose.py                # print once
    python show_pose.py --watch        # refresh in place until Ctrl-C
    python show_pose.py --watch --rate 2
    python show_pose.py --ip 192.168.0.1
"""

import argparse
import math
import time

from rtde_receive import RTDEReceiveInterface

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROBOT_IP = '192.168.0.1'
RATE = 10           # refresh rate in watch mode (Hz)

JOINTS = ['Base', 'Shoulder', 'Elbow', 'Wrist 1', 'Wrist 2', 'Wrist 3']

CLEAR = '\033[H\033[J'  # ANSI: cursor home, clear screen

# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------


def rotvec_to_rpy(rx, ry, rz):
    """Rotation vector (rad) to roll, pitch, yaw (rad).

    Uses the UR convention R = Rz(yaw) * Ry(pitch) * Rx(roll).
    """
    angle = math.sqrt(rx * rx + ry * ry + rz * rz)
    if angle < 1e-12:
        return 0.0, 0.0, 0.0
    kx, ky, kz = rx / angle, ry / angle, rz / angle
    c, s = math.cos(angle), math.sin(angle)
    v = 1 - c

    # Rodrigues: only the matrix entries needed for RPY
    r00 = kx * kx * v + c
    r10 = kx * ky * v + kz * s
    r20 = kx * kz * v - ky * s
    r21 = ky * kz * v + kx * s
    r22 = kz * kz * v + c

    roll = math.atan2(r21, r22)
    pitch = math.atan2(-r20, math.hypot(r00, r10))
    yaw = math.atan2(r10, r00)
    return roll, pitch, yaw


def format_pose(tcp, q):
    """Format a TCP pose [x, y, z, rx, ry, rz] and joint angles q as text."""
    rpy = [math.degrees(a) for a in rotvec_to_rpy(*tcp[3:])]
    lines = ['TCP pose (base frame)']
    for axis, pos, rot, rot_val, ang, ang_val in zip(
            'XYZ', tcp[:3], ['Rx', 'Ry', 'Rz'], tcp[3:],
            ['Roll', 'Pitch', 'Yaw'], rpy):
        lines.append(f'  {axis} {pos * 1000:9.2f} mm    '
                     f'{rot} {rot_val:8.4f} rad    '
                     f'{ang:<5} {ang_val:8.2f}°')
    # Same units as moveL and TARGET in pick_place.py: m and rad
    values = [f'{v:.5f}' for v in tcp[:3]] + [f'{v:.4f}' for v in tcp[3:]]
    lines.append('  Python: [' + ', '.join(values) + ']')

    lines += ['', 'Joints']
    for i in range(0, len(JOINTS), 3):
        lines.append('  ' + '   '.join(
            f'{name:<8} {math.degrees(a):8.2f}°'
            for name, a in zip(JOINTS[i:i + 3], q[i:i + 3])))
    return '\n'.join(lines)


def read(receive):
    return format_pose(receive.getActualTCPPose(), receive.getActualQ())

# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description='Print the UR10 TCP pose and joint angles.')
    parser.add_argument('--watch', action='store_true', help='refresh in place until Ctrl-C')
    parser.add_argument('--rate', type=float, default=RATE, help=f'watch refresh rate in Hz (default {RATE})')
    parser.add_argument('--ip', default=ROBOT_IP, help=f'robot IP (default {ROBOT_IP})')
    args = parser.parse_args()

    receive = RTDEReceiveInterface(args.ip)
    try:
        if not args.watch:
            print(read(receive))
            return
        while True:
            print(CLEAR + read(receive) + '\n\nCtrl-C to quit', flush=True)
            time.sleep(1 / args.rate)
    except KeyboardInterrupt:
        print()
    finally:
        receive.disconnect()


if __name__ == '__main__':
    main()
