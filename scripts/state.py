"""The decider's view of the cell, built only from real readings.

No LLM builds or edits the state, and it never holds the bench's true
contents or injected faults: only the instruction, the gripper reading, where
the TCP is, what earlier skills returned, and counts derived from them.

    tracker = state.Tracker(instruction, poses, approach)
    st = tracker.build(cell.gripper(), cell.tcp())
    options = tracker.options(st)       # e.g. ['pick:A', 'pick:B', 'pick:C', 'home', 'done']
    ...
    tracker.record(result)              # after each skill

State:
    {"step": 3, "instruction": "...",
     "gripper": {"obj": 2, "meaning": "stopped on an object", "pos": 184, "width_mm": 20.0},
     "holding": true, "tcp_at": "B",
     "slots": {"A": {"picks": 1, "gripped": 1, "empty": 0, "placed": 0, "last": "..."}, ...},
     "history": [{"step": 2, "skill": "pick", "args": "B", "ok": true, "reason": null,
                  "gripper": {...}, "tcp_at": "B", "duration_s": 6.3}, ...]}

Options come only from the skill library and slots.json: pick:<slot> when
nothing is held, place:<slot or bin> when something is, home and done always.
"""

import math

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HISTORY = 5             # last skills included in the state
TOL = 0.02              # m, horizontal distance for the TCP to be at a slot
OBJ_MEANING = {0: 'moving', 1: 'stopped on an object while opening',
               2: 'stopped on an object', 3: 'reached the requested position, no object'}
OBJ_STOPPED = 2
NOT_SLOTS = ('home',)   # poses in slots.json that are not bench slots
BINS = ('bin',)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def tcp_at(poses, approach, tcp, tol=TOL):
    """Slot the TCP is at or above (up to its approach height), 'home', or None."""
    for name, pose in poses.items():
        if math.dist(tcp[:2], pose[:2]) > tol:
            continue
        top = pose[2] + approach.get(name, 0.0) + tol
        if name in NOT_SLOTS:
            if abs(tcp[2] - pose[2]) <= tol:
                return name
        elif pose[2] - tol <= tcp[2] <= top:
            return name
    return None


def describe(result):
    """One line on what a skill result measured."""
    skill, arg, gr = result['skill'], result['args'], result['gripper']
    where = f' {arg}' if arg else ''
    if not result['ok']:
        return f'{skill}{where} failed: {result["reason"]}'
    if gr['obj'] == OBJ_STOPPED:
        return f'{skill}{where}: gripper stopped on an object, width {gr["width_mm"]} mm'
    if skill == 'pick':
        return f'{skill}{where}: gripper closed on nothing'
    return f'{skill}{where}: done, gripper {OBJ_MEANING.get(gr["obj"], gr["obj"])}'

# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


class Tracker:
    """Episode memory, from skill results only."""

    def __init__(self, instruction, poses, approach, history=HISTORY):
        self.instruction, self.poses, self.approach = instruction, poses, approach
        self.history = history
        self.step = 0
        self.results = []
        self.slots = {n: {'picks': 0, 'gripped': 0, 'empty': 0, 'placed': 0, 'last': None}
                      for n in poses if n not in NOT_SLOTS}

    def record(self, result, step=None):
        """Add a skill result (step: the step it ran at; default the current one)."""
        entry = dict(result, step=self.step if step is None else step,
                     tcp_at=tcp_at(self.poses, self.approach, result['tcp']))
        self.results.append(entry)
        slot = result['args']
        if result['skill'] in ('pick', 'place') and slot in self.slots and result['ok']:
            s = self.slots[slot]
            if result['skill'] == 'pick':
                s['picks'] += 1
                s['gripped' if result['gripper']['obj'] == OBJ_STOPPED else 'empty'] += 1
            else:
                s['placed'] += 1
            s['last'] = describe(result)
        elif slot in self.slots:
            self.slots[slot]['last'] = describe(result)

    def next_step(self):
        self.step += 1

    def build(self, gripper, tcp):
        """The state for the decider, from the current gripper reading and TCP pose."""
        history = [{k: r[k] for k in ('step', 'skill', 'args', 'ok', 'reason', 'gripper',
                                      'tcp_at', 'duration_s')}
                   for r in self.results[-self.history:]] if self.history else []
        return {'step': self.step, 'instruction': self.instruction,
                'gripper': {'obj': gripper['obj'], 'meaning': OBJ_MEANING.get(gripper['obj']),
                            'pos': gripper['pos'], 'width_mm': gripper['width_mm']},
                'holding': gripper['obj'] == OBJ_STOPPED,
                'tcp_at': tcp_at(self.poses, self.approach, tcp),
                'slots': {n: dict(s) for n, s in self.slots.items()},
                'history': history}

    def options(self, state):
        """Valid next skills: picks when empty-handed, places when holding, home, done."""
        names = list(self.slots)
        if state['holding']:
            opts = [f'place:{n}' for n in names]
        else:
            opts = [f'pick:{n}' for n in names if n not in BINS]
        return opts + ['home', 'done']
