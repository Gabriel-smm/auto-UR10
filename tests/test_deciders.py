"""Deciders: the rules baseline over whole episodes; the model wrapper with mocked answers."""

import pytest

import fake_gripper as g
from decision_rules import RulesDecider
from episode import matches, run


@pytest.fixture(autouse=True)
def instant(monkeypatch):
    monkeypatch.setattr(g, 'MOVE_TIME', 0)
    yield
    g.set_bench(None)


@pytest.mark.parametrize('name', ['nominal', 'single_A', 'single_B', 'single_C', 'empty_bench',
                                  'full_bench', 'wide_only', 'narrow_only', 'similar_widths',
                                  'width_noise_large', 'ghost_always', 'miss_sometimes'])
def test_rules_succeed(name):
    sc, bench, states, decisions = run(RulesDecider(), name)
    assert decisions[-1].choice == 'done'
    assert matches(sc, bench), (bench.blocks(), bench.binned)


def test_rules_probabilities_and_flags():
    _, _, states, decisions = run(RulesDecider(), 'nominal')
    assert [d.choice for d in decisions] == ['pick:A', 'place:C', 'done']
    d = decisions[0]
    assert d.probs['pick:A'] == 1.0 and sum(d.probs.values()) == 1.0
    assert d.last_ok_prob is None and decisions[1].last_ok_prob == 1.0
    assert decisions[-1].task_done_prob == 1.0 and decisions[0].task_done_prob == 0.0


def test_rules_retry_then_give_up_on_miss():
    sc, bench, _, decisions = run(RulesDecider(), 'miss_always')
    assert [d.choice for d in decisions] == ['pick:A', 'pick:A', 'pick:B', 'pick:B',
                                            'pick:C', 'pick:C', 'done']
    assert not matches(sc, bench)


def test_rules_slip_is_seen_but_block_lost():
    sc, bench, states, decisions = run(RulesDecider(), 'slip_always')
    after_pick = states[1]
    assert after_pick['gripper']['obj'] == 3 and not after_pick['holding']     # slip detected
    assert decisions[1].last_ok_prob == 0.0
    assert not matches(sc, bench) and bench.lost


def test_rules_unknown_instruction_is_done():
    d = RulesDecider().decide({'instruction': 'dance', 'holding': False, 'slots': {}, 'history': []},
                              ['home', 'done'])
    assert d.choice == 'done'
