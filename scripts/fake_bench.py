"""Simulated bench for simulator runs: slots, blocks, and what the gripper feels.

URSim simulates the arm but not the blocks. The bench keeps them in memory:
named slots, each with a grip pose (base frame) and an optional block. When
fake_gripper.py closes or opens, it asks the bench, at the current TCP
position, what the real gripper would report:

    close at a slot with a block    gOBJ 2, pos from the block width; block held
    close anywhere else             gOBJ 3, pos at the requested position
    open at an empty slot           block placed there
    open at a bin slot              block gone
    open at an occupied slot or     block dropped (lost)
    away from any slot

pos from a width is interpolated in CALIBRATION, (width mm, pos) points:
one measured on the 2F-85 (73 mm at pos 67, force 0), and the open and
closed ends, which are assumed. Add points as blocks are measured.

Faults, set per scenario and drawn from a generator seeded by the scenario
seed, so a run repeats exactly:

    p_slip          the block falls once the TCP leaves the pick slot.
                    What the status does then is set by slip_signal:
                    'auto' (default) as measured on the 2F-85: unchanged
                    after a close at force 0, gOBJ 3 and pos 228 after a
                    close with force (tested at 100); 'silent' or 'status'
                    force one behaviour
    p_miss          a close at a full slot finds nothing (gOBJ 3)
    width_noise_mm  +- uniform noise on the measured width
    ghost_block     a close on nothing reports an object (gOBJ 2)

Every close, open and injected fault is an event; with a log path, each event
is one line of JSON. Events with a 'fault' field are also kept in
bench.injected.

Scenario file (JSON, in scenarios/):
    {"name": "nominal", "seed": 1,
     "slots_file": "../scripts/slots.json",        # poses by slot name
     "slots": {"A": {"block": {"id": "b1", "width_mm": 40}},
               "C": {},
               "bin": {"bin": true}},
     "faults": {"p_slip": 0.1}, "slip_signal": "auto"}

A slot takes its pose from "pose" or else from slots_file (relative to the
scenario file). Only the slots listed are on the bench.

Command line:
    python fake_bench.py ../scenarios/nominal.json     # print the scenario

As a module:
    import fake_bench
    bench = fake_bench.Bench(fake_bench.load_scenario('scenarios/nominal.json'))
    obj, pos = bench.close([0.2636, 0.3539, -0.0681])
"""

import json
import math
import os
import random
import sys
import time

from fake_gripper import OBJ_REACHED, OBJ_STOPPED, POS_CLOSED, POS_MAX, POS_MIN, POS_OPEN

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TOL = 0.02              # m, the TCP is at a slot within this distance of its pose
STROKE_MM = 85.0        # 2F-85 opening at POS_MIN

# Width (mm) -> pos (counts) when stopped on a block, interpolated between points.
CALIBRATION = [
    (0.0, POS_MAX),     # assumed: closed with nothing between the fingers
    (73.0, 67),         # measured 2026-10-20: 73 mm object, force 0
    (STROKE_MM, POS_MIN),  # assumed: fully open
]
GHOST_WIDTH_MM = 30.0   # width a ghost block reports

FAULTS = {'p_slip': 0.0, 'p_miss': 0.0, 'width_noise_mm': 0.0, 'ghost_block': 0.0}
PROBABILITIES = ('p_slip', 'p_miss', 'ghost_block')
SLIP_SIGNALS = ('auto', 'silent', 'status')

# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


def pos_for(width_mm):
    """Finger position (counts) when stopped on a block of this width, from CALIBRATION."""
    width = max(0.0, min(STROKE_MM, width_mm))
    for (w0, p0), (w1, p1) in zip(CALIBRATION, CALIBRATION[1:]):
        if width <= w1:
            return round(p0 + (width - w0) / (w1 - w0) * (p1 - p0))


def parse_scenario(data, base_dir='.', name=None):
    """Check a scenario dict and fill in defaults and slot poses. Raises ValueError."""
    poses = {}
    if 'slots_file' in data:
        with open(os.path.join(base_dir, data['slots_file'])) as f:
            poses = json.load(f)

    slots = {}
    for slot, entry in data.get('slots', {}).items():
        pose = entry.get('pose', poses.get(slot))
        if pose is None:
            raise ValueError(f'slot {slot!r} has no pose')
        block = entry.get('block')
        if block and not 0 < block.get('width_mm', 0) <= STROKE_MM:
            raise ValueError(f'slot {slot!r}: width_mm must be in (0, {STROKE_MM:g}]')
        if block and entry.get('bin'):
            raise ValueError(f'slot {slot!r}: a bin cannot hold a block')
        slots[slot] = {'pose': list(pose), 'block': dict(block) if block else None,
                       'bin': bool(entry.get('bin'))}

    faults = dict(FAULTS, **data.get('faults', {}))
    unknown = set(faults) - set(FAULTS)
    if unknown:
        raise ValueError(f'unknown faults {sorted(unknown)}: use {sorted(FAULTS)}')
    for key in PROBABILITIES:
        if not 0 <= faults[key] <= 1:
            raise ValueError(f'{key} must be in [0, 1]')

    slip_signal = data.get('slip_signal', 'auto')
    if slip_signal not in SLIP_SIGNALS:
        raise ValueError(f'slip_signal must be one of {SLIP_SIGNALS}')

    return {'name': data.get('name', name or 'unnamed'), 'seed': data.get('seed', 0),
            'slots': slots, 'faults': faults, 'slip_signal': slip_signal}


def load_scenario(path):
    """Read and check a scenario file."""
    with open(path) as f:
        data = json.load(f)
    name = os.path.splitext(os.path.basename(path))[0]
    return parse_scenario(data, os.path.dirname(path), name)

# ---------------------------------------------------------------------------
# Bench
# ---------------------------------------------------------------------------


def _clamp(pos):
    return max(POS_MIN, min(POS_MAX, pos))


class Bench:
    """Bench state for one run. seed overrides the scenario seed."""

    def __init__(self, scenario, seed=None, log_path=None):
        self.name = scenario['name']
        self.seed = scenario['seed'] if seed is None else seed
        self.faults = dict(scenario['faults'])
        self.slip_signal = scenario.get('slip_signal', 'auto')
        self.slots = {n: dict(s, block=dict(s['block']) if s['block'] else None)
                      for n, s in scenario['slots'].items()}
        self.rng = random.Random(self.seed)
        self.held = None            # block between the fingers
        self.held_from = None       # slot it was picked from
        self.stop = None            # pos reported while holding (or on a ghost)
        self.ghost = False          # holding a block that does not exist
        self.slip_pending = False   # held block will fall once the TCP leaves held_from
        self.force = 0              # force of the close that holds the block
        self.binned, self.lost = [], []
        self.events, self.injected = [], []
        self.log_path = log_path
        if log_path:
            os.makedirs(os.path.dirname(log_path) or '.', exist_ok=True)
        self._event('start', faults=self.faults, slip_signal=self.slip_signal,
                    blocks={n: s['block'] for n, s in self.slots.items()})

    def _event(self, event, **fields):
        e = {'t': round(time.time(), 3), 'scenario': self.name, 'seed': self.seed,
             'event': event, **fields}
        self.events.append(e)
        if e.get('fault'):
            self.injected.append(e)
        if self.log_path:
            with open(self.log_path, 'a') as f:
                f.write(json.dumps(e) + '\n')

    def _draw(self, key):
        p = self.faults[key]
        return p > 0 and self.rng.random() < p

    def slot_at(self, xyz, tol=TOL):
        """Name of the nearest slot within tol (m) of xyz, or None."""
        if not self.slots:
            return None
        name = min(self.slots, key=lambda n: math.dist(xyz, self.slots[n]['pose'][:3]))
        return name if math.dist(xyz, self.slots[name]['pose'][:3]) <= tol else None

    def close(self, xyz, target=POS_CLOSED, force=0):
        """Close at xyz toward target; returns (gOBJ, pos) as the gripper would report."""
        tcp = [round(a, 4) for a in xyz]
        if self.held or self.ghost:
            return OBJ_STOPPED, self.stop
        name = self.slot_at(xyz)
        block = name and self.slots[name]['block']
        fault, result = None, (OBJ_REACHED, _clamp(target))
        if block and self._draw('p_miss'):
            fault = 'miss'
        elif block:
            noise = self.rng.uniform(-1, 1) * self.faults['width_noise_mm']
            stop = pos_for(block['width_mm'] + noise)
            if target >= stop:
                self.slots[name]['block'] = None
                self.held, self.held_from, self.stop = block, name, stop
                self.slip_pending = self._draw('p_slip')
                self.force = force
                result = (OBJ_STOPPED, stop)
        elif self._draw('ghost_block'):
            fault = 'ghost'
            self.ghost, self.stop = True, pos_for(GHOST_WIDTH_MM)
            result = (OBJ_STOPPED, self.stop)
        self._event('close', slot=name, tcp=tcp, block=self.held, obj=result[0], pos=result[1],
                    fault=fault)
        return result

    def update(self, xyz):
        """Apply a pending slip once the TCP has left the pick slot.

        Returns the new (gOBJ, pos) when the block falls and slip_signal is
        'status'; None otherwise (a silent slip leaves the status as it was).
        """
        if not self.slip_pending or self.slot_at(xyz) == self.held_from:
            return None
        block, self.held, self.slip_pending = self.held, None, False
        self.lost.append(block)
        signal = self.slip_signal
        if signal == 'auto':
            signal = 'status' if self.force > 0 else 'silent'
        reading = (OBJ_REACHED, POS_MAX) if signal == 'status' else (OBJ_STOPPED, self.stop)
        self._event('slip', slot=self.held_from, tcp=[round(a, 4) for a in xyz], block=block,
                    obj=reading[0], pos=reading[1], force=self.force, signal=signal, fault='slip')
        self.stop = None
        return reading if signal == 'status' else None

    def open(self, xyz, target=POS_OPEN):
        """Open at xyz toward target; returns (gOBJ, pos) as the gripper would report."""
        self.update(xyz)    # a pending slip happens on the way, even if nobody polled
        name = self.slot_at(xyz)
        block, outcome = self.held, None
        if block:
            slot = self.slots.get(name)
            if slot is None or slot['block']:
                outcome = 'dropped'
                self.lost.append(block)
            elif slot['bin']:
                outcome = 'binned'
                self.binned.append(block)
            else:
                outcome = 'placed'
                slot['block'] = block
        self.held = self.held_from = self.stop = None
        self.ghost = self.slip_pending = False
        result = (OBJ_REACHED, _clamp(target))
        self._event('open', slot=name, tcp=[round(a, 4) for a in xyz], block=block,
                    outcome=outcome, obj=result[0], pos=result[1])
        return result

    def blocks(self):
        """Slot name -> block (or None), for checking the end state."""
        return {n: s['block'] for n, s in self.slots.items()}

    def log_info(self):
        """What a run log needs to say about the bench."""
        return {'scenario': self.name, 'seed': self.seed, 'faults': self.faults,
                'injected': self.injected}

# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python fake_bench.py SCENARIO.json')
    sc = load_scenario(sys.argv[1])
    print(f'{sc["name"]}  seed {sc["seed"]}')
    for name, slot in sc['slots'].items():
        x, y, z = (a * 1000 for a in slot['pose'][:3])
        what = 'bin' if slot['bin'] else slot['block'] or 'empty'
        print(f'  {name:<6} x {x:8.1f}  y {y:8.1f}  z {z:8.1f} mm   {what}')
    print('faults', sc['faults'])


if __name__ == '__main__':
    main()
