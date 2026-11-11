"""Skills for the bench: the primitives a decider chooses, and pick/place built from them.

Each skill is planned, then executed. The plan holds the segments and the
safety checks for each, computed before anything moves; a plan that fails a
check is never executed.

Segments that move far (transit: across the bench, to home) are joint moves
(moveJ): a straight line between distant poses can take the shoulder past
its narrowed limit (seen in URSim from above C to home). Short vertical
segments (lift, descend, retreat) are straight lines (moveL), checked with
safety.preflight. A moveJ is checked against the joint limits at both ends
(joints move linearly, so the ends are the extremes) and against the safety
planes at poses sampled along it with the controller's forward kinematics. The result
holds only measured values: the gripper status and TCP pose read at the end.

Primitives (the options a decider sees):

    move:X         lift (if below X's approach height), then move to the approach
                   point above X (A, B, C or bin); the gripper does not change
    down           from above a slot, straight down to its grip pose
    up             from a slot, straight up to its approach point
    close, open    the gripper only; the arm does not move
    home           lift, then move to the home pose

down and up are refused (nothing moves, ok=False) when the TCP is not above or
in a slot. Macros, used by tests and scripts but not offered to deciders:

    pick(slot)     move above the slot, descend, close, lift back
    place(slot)    the same, opening instead of closing
    open_gripper() open the fingers

The approach point is the slot pose raised by approach_z (slots.json,
default 0.10 m) along the base Z axis. Skills make no decisions: no retries,
no choice of the next skill.

Moves are asynchronous so they can be aborted: setting the abort event (or
Ctrl-C) calls stopL and the skill returns ok=False, reason 'aborted'. The
arm stays where it stopped.

As a module:
    import skills
    cell = skills.Cell(control, receive, g, s)
    plan = skills.plan(cell, 'pick', 'A')     # show plan['segments'], plan['preflight']
    result = skills.execute(cell, plan)       # only if plan['ok']
"""

import contextlib
import io
import json
import math
import os
import time

import safety
from grip_width import width_for

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SLOTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'slots.json')
APPROACH_Z = 0.10       # m above a slot, when slots.json gives none
SPEED = 0.1             # m/s, moveL
ACCEL = 0.15            # m/s^2, moveL
JOINT_SPEED = 0.25      # rad/s, moveJ
JOINT_ACCEL = 0.5       # rad/s^2, moveJ
FORCE = 100             # gripper force: with force, a dropped block shows as gOBJ 3
GRIP_SPEED = 64         # gripper speed (0-255)
STOP_DECEL = 2.0        # m/s^2 (stopL) or rad/s^2 (stopJ) on abort
MIN_SEGMENT = 0.001     # m, shorter segments with the same orientation are skipped
START_TOL = 0.005       # m, the arm must still be this close to the plan's start
SLOT_TOL = 0.02         # m, horizontal distance for the TCP to be over a slot
LEVEL_TOL = 0.01        # m, vertical distance for the TCP to be down at a slot's grip pose
POLL = 0.02             # s, async move polling

POS_OPEN, POS_CLOSED = 0, 255
OBJ_STOPPED = 2         # gOBJ: stopped on an object while closing

PRIMITIVES = ('move', 'down', 'up', 'open', 'close', 'home')
SKILLS = PRIMITIVES + ('pick', 'place', 'open_gripper')

# ---------------------------------------------------------------------------
# Cell
# ---------------------------------------------------------------------------


def load_slots(path=SLOTS_FILE):
    """Slot poses and approach heights from slots.json: ({name: pose}, {name: approach_z})."""
    with open(path) as f:
        data = json.load(f)
    approach = data.pop('approach_z', {})
    default = approach.get('default', APPROACH_Z)
    return {n: list(p) for n, p in data.items()}, {n: approach.get(n, default) for n in data}


def where(poses, approach, tcp):
    """(slot, level) of the TCP: level 'down' at the slot's grip pose, 'above' between
    it and the approach height; (None, None) when not over a slot ('home' is not one)."""
    for name, pose in poses.items():
        if name == 'home' or math.dist(tcp[:2], pose[:2]) > SLOT_TOL:
            continue
        if abs(tcp[2] - pose[2]) <= LEVEL_TOL:
            return name, 'down'
        if pose[2] < tcp[2] <= pose[2] + approach[name] + LEVEL_TOL:
            return name, 'above'
    return None, None


def slot_at(poses, xyz, tol=0.02):
    """Nearest slot within tol (m) of xyz, or None."""
    if not poses:
        return None
    name = min(poses, key=lambda n: math.dist(xyz, poses[n][:3]))
    return name if math.dist(xyz, poses[name][:3]) <= tol else None


class Cell:
    """What the skills act on: RTDE interfaces, gripper module and link, slot poses."""

    def __init__(self, control, receive, g, s, slots_file=SLOTS_FILE, speed=SPEED, accel=ACCEL,
                 joint_speed=JOINT_SPEED, joint_accel=JOINT_ACCEL, force=FORCE):
        self.control, self.receive, self.g, self.s = control, receive, g, s
        self.poses, self.approach = load_slots(slots_file)
        self.speed, self.accel, self.force = speed, accel, force
        self.joint_speed, self.joint_accel = joint_speed, joint_accel

    def tcp(self):
        return list(self.receive.getActualTCPPose())

    def q(self):
        return list(self.receive.getActualQ())

    def gripper(self):
        """Current gripper reading: {obj, pos, width_mm}; width only when stopped on an object."""
        st = self.g.status(self.s) or {}
        obj, pos = st.get('obj'), st.get('pos')
        return {'obj': obj, 'pos': pos,
                'width_mm': width_for(pos) if obj == OBJ_STOPPED and pos is not None else None}

# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _round(pose):
    return [round(a, 5) for a in pose]


def _same(a, b):
    return math.dist(a[:3], b[:3]) < MIN_SEGMENT and math.dist(a[3:], b[3:]) < 1e-3


def _raised(pose, z):
    """pose with its Z raised to at least z (base frame)."""
    return [pose[0], pose[1], max(pose[2], z)] + list(pose[3:])


class Refused(Exception):
    """A skill that cannot be planned from where the arm is (for example down when not above a slot)."""


def _slot(cell, arg):
    if arg not in cell.poses or arg == 'home':
        raise ValueError(f'unknown slot {arg!r}: use one of {sorted(n for n in cell.poses if n != "home")}')
    return cell.poses[arg]


def _waypoints(cell, skill, arg, start):
    """(segments before the gripper action, gripper action, segments after). Raises Refused."""
    if skill == 'move':
        target = _slot(cell, arg)
        above = _raised(target, target[2] + cell.approach[arg])
        return [('lift', _raised(start, above[2])), ('transit', above)], None, []
    if skill in ('down', 'up'):
        slot, level = where(cell.poses, cell.approach, start)
        if slot is None:
            raise Refused(f'{skill}: the gripper is not above a slot')
        target = cell.poses[slot]
        if skill == 'down':
            return [('descend', target)], None, []
        return [('retreat', _raised(target, target[2] + cell.approach[slot]))], None, []
    if skill in ('open', 'close'):
        return [], skill, []
    if skill in ('pick', 'place'):
        target = _slot(cell, arg)
        above = _raised(target, target[2] + cell.approach[arg])
        before = [('lift', _raised(start, above[2])), ('transit', above), ('descend', target)]
        return before, 'close' if skill == 'pick' else 'open', [('retreat', above)]
    if skill == 'home':
        home = cell.poses['home']
        return [('lift', _raised(start, home[2])), ('transit', home)], None, []
    if skill == 'open_gripper':
        return [], 'open', []
    raise ValueError(f'unknown skill {skill!r}: use one of {SKILLS}')


def check_movej(control, q_from, q_to):
    """Problems with a moveJ from q_from to q_to, and the printed report.

    Joint limits at both ends; safety planes at PATH_STEPS poses along the
    joint-space line, from the controller's forward kinematics.
    """
    tcp = list(control.getTCPOffset())
    if safety.differences(tcp, safety.ACTIVE_TCP):
        return [f'active TCP {tcp} is not rough_robotiq {safety.ACTIVE_TCP}: '
                'select it on the pendant (Installation > TCP Configuration)'], ''
    margins = {pl['name']: math.inf for pl in safety.PLANES}
    for i in range(safety.PATH_STEPS + 1):
        t = i / safety.PATH_STEPS
        # tcp passed explicitly: in ur_rtde 1.6.5, getForwardKinematics(q) alone returns
        # wrong poses after a getInverseKinematics call (seen in URSim)
        pose = control.getForwardKinematics([a + t * (b - a) for a, b in zip(q_from, q_to)], tcp)
        for name, m in safety.plane_margins(pose):
            margins[name] = min(margins[name], m)
    headroom = [min(a, b) for a, b in zip(safety.joint_headroom(q_from), safety.joint_headroom(q_to))]
    margins, headroom = list(margins.items()), list(zip(safety.JOINTS, headroom))
    return safety.problems_in(margins, headroom), safety.format_scan(margins, headroom)


def plan(cell, skill, arg=None):
    """Plan a skill from the current pose and check every segment. Moves nothing.

    Returns {skill, args, start, segments, gripper, speed, accel, force, preflight, ok, reason}.
    Each segment: {kind, motion: moveL | moveJ, from, to, q_to, after_gripper}.
    """
    start = cell.tcp()
    try:
        before, action, after = _waypoints(cell, skill, arg, start)
    except Refused as e:
        return {'skill': skill, 'args': arg, 'start': _round(start), 'segments': [], 'gripper': None,
                'speed': cell.speed, 'accel': cell.accel, 'joint_speed': cell.joint_speed,
                'joint_accel': cell.joint_accel, 'force': cell.force, 'preflight': [],
                'ok': False, 'reason': str(e)}

    segments, here = [], start
    for i, (kind, pose) in enumerate(before + after):
        if not _same(here, pose):
            segments.append({'kind': kind, 'motion': 'moveJ' if kind == 'transit' else 'moveL',
                             'from': _round(here), 'to': _round(pose),
                             'after_gripper': i >= len(before)})
        here = pose

    checks, problems, q = [], [], cell.q()
    for i, seg in enumerate(segments):
        q_to = cell.control.getInverseKinematics(seg['to'], q)
        seg['q_to'] = list(q_to)
        if seg['motion'] == 'moveJ':
            found, text = check_movej(cell.control, q, q_to)
        else:
            report = io.StringIO()
            with contextlib.redirect_stdout(report):
                found = safety.preflight(cell.control, seg['from'], seg['to'], q, cell.speed)
            text = report.getvalue().strip()
        if not cell.control.isPoseWithinSafetyLimits(seg['to']):
            found.append('target is outside the controller safety limits')
        checks.append({'segment': i, 'kind': seg['kind'], 'motion': seg['motion'],
                       'problems': found, 'report': text})
        problems += [f'{seg["kind"]}: {p}' for p in found]
        q = q_to

    return {'skill': skill, 'args': arg, 'start': _round(start), 'segments': segments,
            'gripper': action, 'speed': cell.speed, 'accel': cell.accel,
            'joint_speed': cell.joint_speed, 'joint_accel': cell.joint_accel, 'force': cell.force,
            'preflight': checks, 'ok': not problems, 'reason': '; '.join(problems) or None}

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _move(cell, seg, abort):
    """Run one segment asynchronously; returns None, 'aborted' or why it was rejected."""
    joint = seg['motion'] == 'moveJ'
    stop = cell.control.stopJ if joint else cell.control.stopL
    try:
        started = (cell.control.moveJ(seg['q_to'], cell.joint_speed, cell.joint_accel, True) if joint
                   else cell.control.moveL(seg['to'], cell.speed, cell.accel, True))
        if not started:
            return 'rejected by the controller'
        while cell.control.getAsyncOperationProgress() >= 0:
            if abort is not None and abort.is_set():
                stop(STOP_DECEL)
                return 'aborted'
            time.sleep(POLL)
    except KeyboardInterrupt:
        stop(STOP_DECEL)
        if abort is not None:
            abort.set()
        return 'aborted'
    return None


def _grip(cell, action):
    pos = POS_CLOSED if action == 'close' else POS_OPEN
    cell.g.move(cell.s, pos, speed=GRIP_SPEED, force=cell.force)


def execute(cell, plan_, abort=None):
    """Run a plan. Returns {skill, args, ok, reason, gripper, tcp, duration_s}, all measured."""
    t0 = time.time()
    reason = None
    if not plan_['ok']:
        reason = plan_['reason']
    elif math.dist(cell.tcp()[:3], plan_['start'][:3]) > START_TOL:
        reason = 'the arm moved since the plan was made: plan again'
    else:
        segments = plan_['segments']
        for seg in [s for s in segments if not s['after_gripper']]:
            reason = reason or _move(cell, seg, abort)
        if not reason and plan_['gripper']:
            _grip(cell, plan_['gripper'])
        for seg in [s for s in segments if s['after_gripper']]:
            reason = reason or _move(cell, seg, abort)
    return {'skill': plan_['skill'], 'args': plan_['args'], 'ok': reason is None, 'reason': reason,
            'gripper': cell.gripper(), 'tcp': _round(cell.tcp()),
            'duration_s': round(time.time() - t0, 3)}


def run(cell, skill, arg=None, abort=None):
    """Plan and, if the plan passes its checks, execute. Returns the result."""
    return execute(cell, plan(cell, skill, arg), abort)


def move(cell, slot, abort=None):
    return run(cell, 'move', slot, abort)


def down(cell, abort=None):
    return run(cell, 'down', None, abort)


def up(cell, abort=None):
    return run(cell, 'up', None, abort)


def close_gripper(cell, abort=None):
    return run(cell, 'close', None, abort)


def pick(cell, slot, abort=None):
    return run(cell, 'pick', slot, abort)


def place(cell, slot, abort=None):
    return run(cell, 'place', slot, abort)


def home(cell, abort=None):
    return run(cell, 'home', None, abort)


def open_gripper(cell, abort=None):
    return run(cell, 'open', None, abort)
