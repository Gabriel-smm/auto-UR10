"""state.py: built from readings only, with the right options."""

import json

import pytest

import fake_gripper as g
import skills
from decision_rules import RulesDecider
from episode import run, setup


@pytest.fixture(autouse=True)
def instant(monkeypatch):
    monkeypatch.setattr(g, 'MOVE_TIME', 0)
    yield
    g.set_bench(None)


def test_initial_state_and_options():
    sc, bench, cell, tracker = setup('nominal')
    st = tracker.build(cell.gripper(), cell.tcp())
    assert st['step'] == 0 and st['instruction'] == 'Move the block in A to C.'
    assert st['tcp_at'] == 'home' and not st['holding'] and st['history'] == []
    assert set(st['slots']) == {'A', 'B', 'C', 'bin'}
    assert tracker.options(st) == ['pick:A', 'pick:B', 'pick:C', 'home', 'done']


def test_after_pick_state_and_options():
    sc, bench, cell, tracker = setup('nominal')
    tracker.record(skills.pick(cell, 'A'))
    tracker.next_step()
    st = tracker.build(cell.gripper(), cell.tcp())
    assert st['holding'] and st['gripper']['obj'] == 2 and st['gripper']['meaning'] == 'stopped on an object'
    assert st['tcp_at'] == 'A'                       # above A, at the approach point
    assert st['slots']['A']['gripped'] == 1 and 'width 39.9 mm' in st['slots']['A']['last']
    assert st['slots']['A']['event'] == 'taken' and st['slots']['B']['event'] is None
    assert st['slots']['A']['width_mm'] == 39.9
    tracker.record(skills.place(cell, 'C'))
    assert tracker.slots['C']['event'] == 'released' and tracker.slots['C']['width_mm'] == 39.9
    assert st['history'][-1]['skill'] == 'pick' and st['history'][-1]['tcp_at'] == 'A'
    assert tracker.options(st) == ['place:A', 'place:B', 'place:C', 'place:bin', 'home', 'done']


def test_history_is_limited():
    sc, bench, cell, tracker = setup('empty_bench')
    for slot in 'ABCABC':
        tracker.record(skills.pick(cell, slot))
        tracker.next_step()
    st = tracker.build(cell.gripper(), cell.tcp())
    assert len(st['history']) == 5 and st['history'][0]['step'] == 1
    assert st['slots']['A']['empty'] == 2 and st['slots']['A']['event'] == 'empty'


@pytest.mark.parametrize('name', ['mixed_faults_seed1', 'ghost_always', 'slip_always'])
def test_state_never_holds_bench_truth(name):
    sc, bench, states, _ = run(RulesDecider(), name)
    ids = [b['id'] for s in sc['slots'].values() if (b := s['block'])]
    for st in states:
        text = json.dumps(st)
        assert not any(k in text for k in ('"bench"', '"injected"', '"fault"', '"id"', 'lost', 'binned'))
        assert not any(f'"{i}"' in text for i in ids)
