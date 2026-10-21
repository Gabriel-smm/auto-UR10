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


# ---------------------------------------------------------------------------
# Model decider: parsing a real answer (fixture), and the real model (-m model)
# ---------------------------------------------------------------------------

import json  # noqa: E402
import os  # noqa: E402

import decision_model  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'sol2b_after_pick.json')


def test_questions_from_options():
    q = decision_model.questions(['pick:A', 'place:bin', 'home', 'done'])
    assert set(q) == {'next_skill', 'last_ok', 'task_done'}
    assert q['next_skill']['type'] == 'choice' and q['last_ok']['type'] == 'noul'
    assert list(q['next_skill']['criteria']) == ['pick:A', 'place:bin', 'home', 'done']
    assert 'bin' in q['next_skill']['criteria']['place:bin']


def test_parse_real_answer():
    fx = json.load(open(FIXTURE))
    d = decision_model.parse(fx['raw'], fx['options'], latency_s=27.4)
    assert d.choice == 'place:C' and d.probs['place:C'] == pytest.approx(0.594, abs=1e-3)
    assert set(d.probs) == set(fx['options'])
    assert d.last_ok_prob == pytest.approx(0.569, abs=1e-3)
    assert d.task_done_prob == pytest.approx(0.744, abs=1e-3)
    assert d.extra['confidence'] == pytest.approx(0.286, abs=1e-3) and d.extra['error'] is None


def test_parse_choice_is_argmax_over_offered_options():
    raw = {'answers': {'next_skill': {'choice': 'teleport', 'probabilities': {'pick:A': 0.3, 'done': 0.6, 'teleport': 0.9}}}}
    d = decision_model.parse(raw, ['pick:A', 'done'])
    assert d.choice == 'done' and d.last_ok_prob is None


def test_parse_answer_without_probabilities_abstains():
    d = decision_model.parse({'answers': {'next_skill': {'error': 'max_length_exceeded'}}}, ['pick:A', 'done'])
    assert d.choice == 'done' and max(d.probs.values()) == 0.0 and d.extra['error'] == 'max_length_exceeded'


@pytest.mark.model
def test_real_model_answers_every_option():
    from episode import setup
    import skills
    sc, bench, cell, tracker = setup('nominal')
    tracker.record(skills.pick(cell, 'A'))
    st = tracker.build(cell.gripper(), cell.tcp())
    options = tracker.options(st)
    decider = decision_model.ModelDecider(device=os.environ.get('UR10_MODEL_DEVICE', 'cpu'))
    d = decider.decide(st, options)
    assert set(d.probs) == set(options) and d.choice in options
    assert sum(d.probs.values()) == pytest.approx(1.0, abs=0.02)
    assert 0 <= d.last_ok_prob <= 1 and 0 <= d.task_done_prob <= 1
