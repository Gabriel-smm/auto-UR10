"""A minimal decide -> skill loop over fake_arm + fake_gripper + fake_bench, for tests."""

import os

import fake_arm
import fake_bench
import fake_gripper as g
import skills
import state as state_mod
from decision import split

SCENARIOS = os.path.join(os.path.dirname(__file__), '..', 'scenarios')


def setup(name, seed=None, **faults):
    sc = fake_bench.load_scenario(os.path.join(SCENARIOS, f'{name}.json'))
    sc['faults'].update(faults)
    bench = fake_bench.Bench(sc, seed)
    poses, approach = skills.load_slots()
    receive = fake_arm.FakeReceive(poses['home'])
    control = fake_arm.FakeControl(receive)
    g.set_bench(bench, receive.getActualTCPPose)
    s = g.connect()
    g.activate(s)
    cell = skills.Cell(control, receive, g, s)
    tracker = state_mod.Tracker(sc['instruction'], poses, approach)
    return sc, bench, cell, tracker


def run(decider, name, max_steps=60, seed=None, **faults):
    """Returns (scenario, bench, states, decisions)."""
    sc, bench, cell, tracker = setup(name, seed, **faults)
    states, decisions = [], []
    for _ in range(max_steps):
        st = tracker.build(cell.gripper(), cell.tcp())
        d = decider.decide(st, tracker.options(st))
        states.append(st)
        decisions.append(d)
        if d.choice == 'done':
            break
        skill, arg = split(d.choice)
        tracker.record(skills.run(cell, skill, arg))
        tracker.next_step()
    return sc, bench, states, decisions


def matches(sc, bench):
    exp = sc['expected']
    slots = {n: (b or {}).get('id') for n, b in bench.blocks().items() if n in exp['slots']}
    return slots == exp['slots'] and sorted(b['id'] for b in bench.binned) == sorted(exp['binned'])
