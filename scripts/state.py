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
     "slots": {"A": {"picks": 1, "gripped": 1, "empty": 0, "placed": 0, "event": "taken",
                     "width_mm": 39.9, "last": "..."}, ...},
     "history": [{"step": 2, "skill": "pick", "args": "B", "ok": true, "reason": null,
                  "gripper": {...}, "tcp_at": "B", "duration_s": 6.3}, ...]}

Options come only from the skill library and slots.json, and are all offered
at every step (no guard): move:<slot or bin>, down, up, open, close, home, done.
Slot events come from the primitives: a close while down at a slot is a pick
(taken or empty), an open while down at a slot, or anywhere over the bin,
after holding a block is a place (released).
"""

import math

from skills import where

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
EVENTS = ('taken', 'empty', 'released', 'failed')   # latest event at a slot, from its last result
OPEN_BELOW = 128        # gripper pos under which an empty gripper reads as open
PRIMITIVE_OPTIONS = ('down', 'up', 'open', 'close', 'home', 'done')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def locate(poses, approach, tcp, tol=TOL):
    """(slot, level) of the TCP: level 'down' or 'above' a slot; ('home', None) at home;
    (None, None) elsewhere."""
    slot, level = where(poses, approach, tcp)
    if slot:
        return slot, level
    home = poses.get('home')
    if home and math.dist(tcp[:3], home[:3]) <= tol:
        return 'home', None
    return None, None


def tcp_at(poses, approach, tcp, tol=TOL):
    """Slot the TCP is at or above (up to its approach height), 'home', or None."""
    return locate(poses, approach, tcp, tol)[0]


def closed_empty(gripper):
    """The gripper reached a closed position with nothing in it."""
    return gripper['obj'] == 3 and gripper['pos'] is not None and gripper['pos'] >= OPEN_BELOW


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
        self.held_width = None      # width of the block taken by the last gripped pick
        self.holding = False        # the gripper reading after the last skill was gOBJ 2
        self.slots = {n: {'picks': 0, 'gripped': 0, 'empty': 0, 'placed': 0, 'event': None,
                          'width_mm': None, 'last': None}
                      for n in poses if n not in NOT_SLOTS}

    def _pick(self, slot, result):
        s = self.slots[slot]
        s['picks'] += 1
        gripped = result['gripper']['obj'] == OBJ_STOPPED
        s['gripped' if gripped else 'empty'] += 1
        s['event'] = 'taken' if gripped else 'empty'
        s['width_mm'] = self.held_width = result['gripper']['width_mm'] if gripped else None

    def _place(self, slot):
        s = self.slots[slot]
        s['placed'] += 1
        s['event'], s['width_mm'], self.held_width = 'released', self.held_width, None

    def record(self, result, step=None):
        """Add a skill result (step: the step it ran at; default the current one)."""
        at, level = locate(self.poses, self.approach, result['tcp'])
        entry = dict(result, step=self.step if step is None else step, tcp_at=at, tcp_level=level)
        self.results.append(entry)
        was_holding, self.holding = self.holding, result['gripper']['obj'] == OBJ_STOPPED
        skill, ok = result['skill'], result['ok']
        if skill in ('close', 'open'):
            if ok and skill == 'close' and at in self.slots and level == 'down':
                self._pick(at, result)
                self.slots[at]['last'] = describe(result)
            elif ok and skill == 'open' and was_holding and at in self.slots and \
                    (level == 'down' or at in BINS):
                self._place(at)
                self.slots[at]['last'] = describe(result)
            return
        slot = result['args'] if skill in ('pick', 'place') else at
        if skill in ('pick', 'place') and slot in self.slots and ok:
            self._pick(slot, result) if skill == 'pick' else self._place(slot)
            self.slots[slot]['last'] = describe(result)
        elif slot in self.slots and not ok:
            self.slots[slot]['last'] = describe(result)
            if not result['ok']:
                self.slots[slot]['event'] = 'failed'

    def next_step(self):
        self.step += 1

    def build(self, gripper, tcp):
        """The state for the decider, from the current gripper reading and TCP pose."""
        history = [{k: r[k] for k in ('step', 'skill', 'args', 'ok', 'reason', 'gripper',
                                      'tcp_at', 'tcp_level', 'duration_s')}
                   for r in self.results[-self.history:]] if self.history else []
        at, level = locate(self.poses, self.approach, tcp)
        return {'step': self.step, 'instruction': self.instruction,
                'gripper': {'obj': gripper['obj'], 'meaning': OBJ_MEANING.get(gripper['obj']),
                            'pos': gripper['pos'], 'width_mm': gripper['width_mm']},
                'holding': gripper['obj'] == OBJ_STOPPED,
                'tcp_at': at, 'tcp_level': level,
                'slots': {n: dict(s) for n, s in self.slots.items()},
                'history': history}

    def options(self, state=None):
        """Every primitive, at every step: move to each slot and the bin, down, up, open,
        close, home, done. No guard: a decider may choose one that does nothing useful."""
        return [f'move:{n}' for n in self.slots] + list(PRIMITIVE_OPTIONS)
