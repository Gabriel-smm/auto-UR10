"""Stand-in for gripper.py, for runs against the simulator (URSim).

URSim does not simulate the Robotiq 2F-85, so the motion scripts use this
module instead of gripper.py when they target the simulator. It has the same
public functions and constants and returns status dicts with the same keys,
but keeps the gripper's state in memory: it opens no port and never imports
serial.

Closing ends according to the scenario, the object between the fingers:

    object   gOBJ                     pos
    wide     2 (stopped on object)    about 120
    narrow   2 (stopped on object)    about 205
    none     3 (reached position)     about 228

These positions are placeholders until measured on the real gripper with the
real blocks. pos gets +-NOISE counts of random noise; set the seed for
repeatable runs.

With a bench (fake_bench.py) set, the bench decides instead, from the TCP
position at the time of the move: what is in the slot there, and its width.
The position comes from URSim (getActualTCPPose) or from a function passed in.

A move reports gOBJ = 0 (moving) for MOVE_TIME seconds before its result.

Command line (same commands as gripper.py):
    python fake_gripper.py status
    UR10_SIM_OBJECT=wide UR10_SIM_SEED=1 python fake_gripper.py close

As a module:
    import fake_gripper as g
    g.set_object('narrow')          # or None; set_object_source(fn) for a world model
    g.set_seed(1)
    g.set_bench(bench)              # or set_bench(bench, pose_fn) without URSim
    s = g.connect()
    g.activate(s)
    print(g.close(s))
"""

import os
import random
import sys
import time

# Same constants and frame helpers as the real driver (gripper.py imports
# serial only inside its connect(), so nothing serial is loaded here)
from gripper import (ACT_ACTIVATE, ACT_GOTO, ACT_RESET, ADDR, BAUD, OBJ_MOVING,
                     POS_CLOSED, POS_OPEN, STA_ACTIVATED, TIMEOUT, crc, frame)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = 'fake'

# Scenario: object kind -> (gOBJ, pos) at the end of a close.
# Placeholders until measured on the real gripper with the real blocks.
OBJ_STOPPED = 2     # gOBJ: stopped on an object while closing
OBJ_REACHED = 3     # gOBJ: reached the requested position
SCENARIOS = {
    'wide': (OBJ_STOPPED, 120),
    'narrow': (OBJ_STOPPED, 205),
    None: (OBJ_REACHED, 228),
}

POS_MIN = 3         # observed fully open
POS_MAX = 228       # observed fully closed, no object
NOISE = 2           # +- counts added to pos

STA_IN_PROGRESS = 1  # gSTA: activation in progress
ACTIVATE_POLLS = 1   # status polls that report gSTA = 1 before activation completes
MOVE_POLLS = 1       # status polls that report gOBJ = 0 (moving) before a move ends
MOVE_TIME = 0.5      # s, at least this long before a move ends
POLL = 0.01          # wait() poll interval (s)

ENV_OBJECT = 'UR10_SIM_OBJECT'  # wide | narrow | none
ENV_SEED = 'UR10_SIM_SEED'      # integer

# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


def _kind(name):
    kind = None if name in (None, '', 'none') else name
    if kind not in SCENARIOS:
        raise ValueError(f'unknown object {name!r}: use wide, narrow or none')
    return kind


def set_object(name):
    """Fix the object between the fingers: 'wide', 'narrow' or None."""
    kind = _kind(name)
    set_object_source(lambda: kind)


def set_object_source(fn):
    """Ask fn() for the object kind at each close, for example from a world model."""
    global _source
    _source = fn


def set_seed(seed):
    """Seed the pos noise, for repeatable runs (None: unseeded)."""
    global _rng
    _rng = random.Random(seed)


def _noisy(pos):
    return max(0, min(255, pos + _rng.randint(-NOISE, NOISE)))


def set_bench(bench, pose_fn=None):
    """Take close and open results from a fake_bench.Bench (None: back to the object).

    pose_fn() returns the TCP pose; by default it is read from URSim with
    RTDEReceiveInterface, connected on first use.
    """
    global _bench, _pose
    _bench, _pose = bench, pose_fn or _sim_pose


def _sim_pose():
    global _receive
    if _receive is None:
        from rtde_receive import RTDEReceiveInterface
        from robot import SIM_IP
        _receive = RTDEReceiveInterface(SIM_IP)
    return _receive.getActualTCPPose()


def _release_pose():
    global _receive
    if _receive is not None:
        _receive.disconnect()
        _receive = None


_receive = None
set_bench(None)
set_object(os.environ.get(ENV_OBJECT))
set_seed(int(os.environ[ENV_SEED]) if os.environ.get(ENV_SEED) else None)

# ---------------------------------------------------------------------------
# Gripper commands
# ---------------------------------------------------------------------------


class FakeLink:
    """In-memory gripper state, in place of the serial port."""

    def __init__(self):
        self.act = self.goto = self.sta = self.obj = 0
        self.fault = self.current = 0
        self.pos = POS_MIN
        self.polls = 0        # status polls that still report the old state
        self.result = None    # dict of fields to set when polls reach 0
        self.done = 0.0       # time.time() before which a move is still running

    def close(self):
        _release_pose()


def connect(port=PORT):
    """Return a fresh, not yet activated fake gripper."""
    return FakeLink()


def write(s, action, pos=0, speed=0, force=0):
    """Set the state as the three output registers would. Returns the reply frame."""
    if action == ACT_RESET:
        s.act = s.goto = s.sta = s.obj = 0
        s.polls, s.result = 0, None
    elif action == ACT_ACTIVATE:
        s.act, s.sta = 1, STA_IN_PROGRESS
        s.polls, s.result = ACTIVATE_POLLS, {'sta': STA_ACTIVATED, 'pos': _noisy(POS_MIN)}
        s.done = 0.0
    elif action == ACT_GOTO and s.sta == STA_ACTIVATED:
        # Like the real gripper, a move is ignored until activation is complete
        s.goto, s.obj = 1, OBJ_MOVING
        s.polls, s.result = MOVE_POLLS, _move_result(s, pos, force)
        s.done = time.time() + MOVE_TIME
    return frame(bytes([0x10, 0x03, 0xE8, 0x00, 0x03]))


def _move_result(s, pos, force):
    if _bench:
        xyz = _pose()[:3]
        obj, stop = _bench.close(xyz, pos, force) if pos > s.pos else _bench.open(xyz, pos)
        return {'obj': obj, 'pos': stop}
    obj, stop = SCENARIOS[_kind(_source())]
    if obj == OBJ_STOPPED and pos > stop:
        return {'obj': obj, 'pos': _noisy(stop)}
    return {'obj': OBJ_REACHED, 'pos': _noisy(max(POS_MIN, min(POS_MAX, pos)))}


def status(s):
    """Advance the state by one poll and return it, as gripper.status does."""
    if s.polls:
        s.polls -= 1
    elif s.result and time.time() >= s.done:
        for key, value in s.result.items():
            setattr(s, key, value)
        s.result = None
    elif _bench and _bench.slip_pending and not s.result:
        lost = _bench.update(_pose()[:3])
        if lost:
            s.obj, s.pos = lost
    return {'act': s.act, 'goto': s.goto, 'sta': s.sta, 'obj': s.obj,
            'fault': s.fault, 'pos': s.pos, 'current': s.current}


def wait(s, test, secs):
    """Poll status until test(status) is true or secs elapse. Returns last status."""
    start = time.time()
    st = None
    while time.time() - start < secs:
        st = status(s)
        if st and test(st):
            break
        time.sleep(POLL)
    return st


def activate(s, secs=15):
    """Reset then activate; returns once gSTA reaches 3."""
    write(s, ACT_RESET)
    write(s, ACT_ACTIVATE)
    return wait(s, lambda st: st['sta'] == STA_ACTIVATED, secs)


def move(s, pos, speed=64, force=0, secs=8):
    """Move to pos (0-255) and wait until the motion ends or an object is hit."""
    write(s, ACT_GOTO, pos, speed, force)
    return wait(s, lambda st: st['obj'] != OBJ_MOVING, secs)


def open_(s, **kw):
    return move(s, POS_OPEN, **kw)


def close(s, **kw):
    return move(s, POS_CLOSED, **kw)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    commands = {
        'status': status,
        'activate': activate,
        'open': open_,
        'close': close,
    }
    if cmd not in commands:
        raise SystemExit(f'Usage: python fake_gripper.py [{"|".join(commands)}]')

    s = connect()
    try:
        if cmd in ('open', 'close'):
            activate(s)   # each run starts a fresh, unactivated gripper
        print(commands[cmd](s))
    finally:
        s.close()


if __name__ == '__main__':
    main()
