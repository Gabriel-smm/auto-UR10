"""The UR10's safety configuration, and software checks against it.

The constants below are transcribed from the active PolyScope installation
(backups/miniro_2safety.installation, safety checksum CRC 313597321). The UR
controller enforces these limits; the checks here only refuse a move early,
with a margin, before the controller would stop the robot.

Safety planes: each plane stores a unit normal n and a distance d, with the
displacement already included in d. The normal points to the allowed side
(the plane feature's +Z, by the right-hand rule over its taught points,
points into the prohibited side), so for a point p:

    margin = n·p + d     positive: allowed, zero: on the limit

On a CB3 the planes restrict one point only: the flange plus PLANE_TCP.

Read-only: nothing here sends motion commands. `watch` uses
RTDEReceiveInterface only and can run while jogging on the pendant.

Command line:
    python safety.py show                                       # print the limits
    python safety.py compare ../backups/miniro_2safety.installation
    python safety.py watch                                      # live margins until Ctrl-C
    python safety.py watch --rate 2 --ip 192.168.0.1

As a module (from the motion scripts):
    problems = safety.check_move(start, target, q_start, ik=control.getInverseKinematics)
"""

import argparse
import gzip
import json
import math
import sys
import time
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Safety configuration (from the installation, CRC 313597321)
# ---------------------------------------------------------------------------

CHECKSUM_CRC = 313597321

# TCP speed (m/s), force (N), power (W), momentum (kg m/s)
NORMAL = {'tcp_speed': 1.5, 'force': 150.0, 'power': 300.0, 'momentum': 25.0}
REDUCED = {'tcp_speed': 0.75, 'force': 120.0, 'power': 200.0, 'momentum': 10.0}

JOINTS = ['Base', 'Shoulder', 'Elbow', 'Wrist 1', 'Wrist 2', 'Wrist 3']

# Joint position limits, Normal mode (rad). Only the shoulder is narrowed.
# Reduced mode uses -363..363 deg on every joint.
JOINT_MIN = [math.radians(a) for a in [-363, -363, -363, -363, -363, -363]]
JOINT_MAX = [math.radians(a) for a in [363, -51, 363, 363, 363, 363]]

# Active planes, mode BOTH (Normal and Reduced). distance includes displacement.
PLANES = [
    {'name': 'backwall', 'normal': [1.3575948862069154e-4, 0.9972389660472237, 0.07425918237110479],
     'distance': 0.3442227080245446, 'displacement': 0.01},
    {'name': 'leftwall', 'normal': [-0.9790978769679337, 0.11716231836778303, -0.16625383746419628],
     'distance': 0.7333144836997104, 'displacement': 0.02},
    {'name': 'Base', 'normal': [-6.618981952777791e-4, 1.5666852888883147e-5, 0.9999997808226404],
     'distance': 0.16412416899420018, 'displacement': 0.09},
]

PLANE_TCP = [0.0, 0.0, 0.1628, 0.0, 0.0, 0.0]   # point the planes are checked at, from the flange
ACTIVE_TCP = [0.0, 0.0, 0.1658, 0.0, 0.0, 0.0]  # TCP 'rough_robotiq': what getActualTCPPose reports
PAYLOAD = 1.8                                    # kg

# ---------------------------------------------------------------------------
# Software margins (on top of the controller's limits)
# ---------------------------------------------------------------------------

PLANE_MARGIN = 0.03               # m, refuse a path closer than this to a plane
JOINT_MARGIN = math.radians(3)    # rad, refuse a path closer than this to a joint limit
PATH_STEPS = 50                   # samples along a moveL path

ROBOT_IP = '192.168.0.1'
RATE = 10                         # watch refresh rate (Hz)
CLEAR = '\033[H\033[J'            # ANSI: cursor home, clear screen

SAFETY_MODES = {1: 'NORMAL', 2: 'REDUCED', 3: 'PROTECTIVE_STOP', 4: 'RECOVERY',
                5: 'SAFEGUARD_STOP', 6: 'SYSTEM_EMERGENCY_STOP',
                7: 'ROBOT_EMERGENCY_STOP', 8: 'VIOLATION', 9: 'FAULT'}

# ---------------------------------------------------------------------------
# Pose maths (poses are [x, y, z, rx, ry, rz], rotation vector in rad)
# ---------------------------------------------------------------------------


def rotvec_to_matrix(r):
    angle = math.sqrt(sum(a * a for a in r))
    if angle < 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    kx, ky, kz = (a / angle for a in r)
    c, s = math.cos(angle), math.sin(angle)
    v = 1 - c
    return [[kx * kx * v + c, kx * ky * v - kz * s, kx * kz * v + ky * s],
            [kx * ky * v + kz * s, ky * ky * v + c, ky * kz * v - kx * s],
            [kx * kz * v - ky * s, ky * kz * v + kx * s, kz * kz * v + c]]


def matrix_to_rotvec(m):
    cos = max(-1.0, min(1.0, (m[0][0] + m[1][1] + m[2][2] - 1) / 2))
    angle = math.acos(cos)
    if angle < 1e-9:
        return [0.0, 0.0, 0.0]
    if math.pi - angle < 1e-6:
        # Near 180 deg: axis from the diagonal, signs from the off-diagonal terms
        k = [math.sqrt(max(0.0, (m[i][i] + 1) / 2)) for i in range(3)]
        i = k.index(max(k))
        for j in range(3):
            if j != i:
                k[j] = math.copysign(k[j], m[i][j] + m[j][i])
        return [angle * a for a in k]
    s = 2 * math.sin(angle)
    return [angle * (m[2][1] - m[1][2]) / s,
            angle * (m[0][2] - m[2][0]) / s,
            angle * (m[1][0] - m[0][1]) / s]


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def transpose(m):
    return [list(row) for row in zip(*m)]


def apply(m, v):
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def pose_trans(pose, offset):
    """Offset expressed in the pose's frame, like URScript pose_trans."""
    r = rotvec_to_matrix(pose[3:])
    pos = [p + d for p, d in zip(pose[:3], apply(r, offset[:3]))]
    return pos + matrix_to_rotvec(matmul(r, rotvec_to_matrix(offset[3:])))


def pose_inv(pose):
    rt = transpose(rotvec_to_matrix(pose[3:]))
    return [-a for a in apply(rt, pose[:3])] + matrix_to_rotvec(rt)


def interpolate(a, b, t):
    """Pose at fraction t of a straight-line (moveL) move from a to b."""
    ra = rotvec_to_matrix(a[3:])
    rel = matrix_to_rotvec(matmul(transpose(ra), rotvec_to_matrix(b[3:])))
    rot = matmul(ra, rotvec_to_matrix([t * x for x in rel]))
    return [pa + t * (pb - pa) for pa, pb in zip(a[:3], b[:3])] + matrix_to_rotvec(rot)

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def plane_point(tcp_pose):
    """Point the safety planes are checked at, from a pose of the active TCP."""
    flange = pose_trans(tcp_pose, pose_inv(ACTIVE_TCP))
    return pose_trans(flange, PLANE_TCP)[:3]


def plane_margins(tcp_pose):
    """Signed distance (m) to each plane; positive means allowed."""
    p = plane_point(tcp_pose)
    return [(pl['name'], sum(n * x for n, x in zip(pl['normal'], p)) + pl['distance'])
            for pl in PLANES]


def joint_headroom(q):
    """Distance (rad) from each joint to its nearer limit; negative means past it."""
    return [min(a - lo, hi - a) for a, lo, hi in zip(q, JOINT_MIN, JOINT_MAX)]


def scan_move(start, target, q_start=None, ik=None):
    """Smallest plane margin and joint headroom along a moveL from start to target.

    ik(pose, qnear) returns joint angles (for example
    RTDEControlInterface.getInverseKinematics); without it, joints are skipped.
    Returns (margins, headroom): lists of (name, value); headroom is None
    without ik.
    """
    margins = {pl['name']: math.inf for pl in PLANES}
    headroom = [math.inf] * len(JOINTS) if ik else None
    q = q_start
    for i in range(PATH_STEPS + 1):
        pose = interpolate(start, target, i / PATH_STEPS)
        for name, m in plane_margins(pose):
            margins[name] = min(margins[name], m)
        if ik:
            q = ik(pose, q) if q is not None else ik(pose)
            headroom = [min(h, r) for h, r in zip(headroom, joint_headroom(q))]
    return list(margins.items()), headroom and list(zip(JOINTS, headroom))


def check_move(start, target, q_start=None, ik=None):
    """Problems (list of strings, empty if none) with a moveL from start to target."""
    return problems_in(*scan_move(start, target, q_start, ik))


def problems_in(margins, headroom):
    problems = [f'path comes within {m * 1000:.0f} mm of safety plane {name} '
                f'(minimum {PLANE_MARGIN * 1000:.0f} mm)'
                for name, m in margins if m < PLANE_MARGIN]
    problems += [f'path takes {name} within {math.degrees(h):.1f}° of its limit '
                 f'(minimum {math.degrees(JOINT_MARGIN):.0f}°)'
                 for name, h in headroom or [] if h < JOINT_MARGIN]
    return problems


def format_scan(margins, headroom=None):
    lines = ['Smallest along the path',
             '  plane margin   ' + '   '.join(f'{name} {m * 1000:.0f} mm' for name, m in margins)]
    if headroom:
        name, h = min(headroom, key=lambda x: x[1])
        lines.append(f'  joint headroom {name} {math.degrees(h):.1f}°')
    return '\n'.join(lines)


def preflight(control, start, target, q_start, speed):
    """Checks before a moveL from start to target with an RTDEControlInterface.

    Prints the smallest margins along the path and returns a list of
    problems (empty if the move may go ahead).
    """
    tcp = list(control.getTCPOffset())
    if differences(tcp, ACTIVE_TCP):
        return [f'active TCP {tcp} is not rough_robotiq {ACTIVE_TCP}: '
                'select it on the pendant (Installation > TCP Configuration)']
    problems = []
    if speed > REDUCED['tcp_speed']:
        problems.append(f'speed {speed} m/s is above the Reduced-mode limit {REDUCED["tcp_speed"]} m/s')
    margins, headroom = scan_move(start, target, q_start, control.getInverseKinematics)
    print(format_scan(margins, headroom))
    return problems + problems_in(margins, headroom)

# ---------------------------------------------------------------------------
# Installation file
# ---------------------------------------------------------------------------


def expected():
    """The constants above, in the structure parse_installation returns."""
    return {'crc': CHECKSUM_CRC, 'normal': NORMAL, 'reduced': REDUCED,
            'joint_min': JOINT_MIN, 'joint_max': JOINT_MAX,
            'planes': [{k: pl[k] for k in ('name', 'normal', 'distance', 'displacement')}
                       for pl in PLANES],
            'plane_tcp': PLANE_TCP, 'tcp': ACTIVE_TCP, 'payload': PAYLOAD}


def parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def parse_installation(path):
    """Read the safety settings, active TCP and payload from a .installation file."""
    with gzip.open(path) as f:
        root = ET.parse(f).getroot()

    sections, current = {}, None
    for line in root.find('SafetySettings').text.splitlines():
        line = line.strip()
        if line.startswith('['):
            current = sections.setdefault(line[1:-1], {})
        elif '=' in line:
            key, value = line.split('=', 1)
            current[key.strip()] = parse_value(value.strip())

    def limits(sec):
        return {'tcp_speed': sec['maxTcpSpeed'], 'force': sec['maxForce'],
                'power': sec['maxPower'], 'momentum': sec['maxMomentum']}

    # Joint positions are stored as revolutions * 2 pi + angle
    joints = sections['SafetyLimits Normal Joints']
    joint_min = [r * 2 * math.pi + a for r, a in zip(joints['minJointRevolutions'], joints['minJointPosition'])]
    joint_max = [r * 2 * math.pi + a for r, a in zip(joints['maxJointRevolutions'], joints['maxJointPosition'])]

    planes, plane_tcp = [], None
    for name, sec in sections.items():
        if name.startswith('SafetyLimits BoundaryPlane') and sec['mode'] != 'DISABLED':
            planes.append({'name': sec['name'], 'normal': sec['planeNormal'],
                           'distance': sec['distanceToOrigin'], 'displacement': sec['displacement']})
            plane_tcp = sec['tcpOffset']

    tcp_settings = root.find('TCPSettings')
    active = tcp_settings.get('activePose')
    tcp = next(t for t in tcp_settings.iter('tcp') if t.get('name') == active)

    return {'crc': sections['Safety Checksum']['crc'],
            'normal': limits(sections['SafetyLimits Normal Values']),
            'reduced': limits(sections['SafetyLimits Reduced Values']),
            'joint_min': joint_min, 'joint_max': joint_max,
            'planes': planes, 'plane_tcp': plane_tcp,
            'tcp': [float(x) for x in tcp.get('offset').split(',')],
            'payload': float(tcp_settings.get('toolPayload'))}


def differences(a, b, path=''):
    """List of 'path: a != b' strings, comparing numbers to 1e-6."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b))
                for d in differences(a.get(k), b.get(k), f'{path}.{k}' if path else k)]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f'{path}[{i}]')]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return [] if abs(a - b) < 1e-6 else [f'{path}: file {a} != script {b}']
    return [] if a == b else [f'{path}: file {a} != script {b}']


def compare(path):
    """Print differences between an installation file and the constants; return their count."""
    found = parse_installation(path)
    print(f'{path}: safety checksum CRC {found["crc"]}')
    diffs = differences(found, expected())
    print('\n'.join(diffs) if diffs else 'matches safety.py')
    return len(diffs)

# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def show():
    print(f'Safety checksum CRC {CHECKSUM_CRC}\n')
    for mode, lim in (('Normal', NORMAL), ('Reduced', REDUCED)):
        print(f'{mode:<8} TCP {lim["tcp_speed"]} m/s   force {lim["force"]:.0f} N   '
              f'power {lim["power"]:.0f} W   momentum {lim["momentum"]:.0f} kg m/s')
    print('\nJoint limits, Normal mode')
    for name, lo, hi in zip(JOINTS, JOINT_MIN, JOINT_MAX):
        print(f'  {name:<9} {math.degrees(lo):7.1f}° .. {math.degrees(hi):6.1f}°')
    print(f'\nSafety planes (checked at flange + {PLANE_TCP[2] * 1000:.1f} mm; margin = n·p + d)')
    for pl in PLANES:
        n = ', '.join(f'{a:.4f}' for a in pl['normal'])
        print(f'  {pl["name"]:<9} n ({n})   d {pl["distance"] * 1000:.1f} mm   '
              f'displacement {pl["displacement"] * 1000:.0f} mm')
    print(f'\nActive TCP {ACTIVE_TCP[2] * 1000:.1f} mm along tool Z, payload {PAYLOAD} kg')
    print(f'Software margins: {PLANE_MARGIN * 1000:.0f} mm to planes, '
          f'{math.degrees(JOINT_MARGIN):.0f}° to joint limits')


def watch(ip, rate):
    from rtde_receive import RTDEReceiveInterface

    receive = RTDEReceiveInterface(ip)
    try:
        while True:
            tcp, q = receive.getActualTCPPose(), receive.getActualQ()
            mode = receive.getSafetyMode()
            lines = [f'Safety mode {SAFETY_MODES.get(mode, mode)}', '', 'Plane margins']
            lines += [f'  {name:<9} {m * 1000:8.1f} mm' + ('   < margin' if m < PLANE_MARGIN else '')
                      for name, m in plane_margins(tcp)]
            lines += ['', 'Joint headroom']
            lines += [f'  {name:<9} {math.degrees(a):8.2f}°   {math.degrees(h):7.1f}° to limit'
                      + ('   < margin' if h < JOINT_MARGIN else '')
                      for name, a, h in zip(JOINTS, q, joint_headroom(q))]
            print(CLEAR + '\n'.join(lines) + '\n\nCtrl-C to quit', flush=True)
            time.sleep(1 / rate)
    except KeyboardInterrupt:
        print()
    finally:
        receive.disconnect()


def main():
    parser = argparse.ArgumentParser(description='UR10 safety limits and software checks.')
    sub = parser.add_subparsers(dest='cmd')
    sub.add_parser('show', help='print the limits (default)')
    p = sub.add_parser('compare', help='compare an exported .installation with safety.py')
    p.add_argument('path')
    p = sub.add_parser('watch', help='live plane margins and joint headroom (read-only)')
    p.add_argument('--rate', type=float, default=RATE, help=f'refresh rate in Hz (default {RATE})')
    p.add_argument('--ip', default=ROBOT_IP, help=f'robot IP (default {ROBOT_IP})')
    args = parser.parse_args()

    if args.cmd == 'compare':
        sys.exit(1 if compare(args.path) else 0)
    elif args.cmd == 'watch':
        watch(args.ip, args.rate)
    else:
        show()


if __name__ == '__main__':
    main()
