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
FIXTURE_D3 = os.path.join(os.path.dirname(__file__), 'fixtures', 'd3lite_after_pick.json')


def test_questions_from_options():
    q = decision_model.questions(['pick:A', 'place:bin', 'home', 'done'])
    assert set(q) == {'next_skill', 'last_ok', 'task_done'}
    assert q['next_skill']['type'] == 'choice' and q['last_ok']['type'] == 'noul'
    assert list(q['next_skill']['criteria']) == ['pick:A', 'place:bin', 'home', 'done']
    assert 'bin' in q['next_skill']['criteria']['place:bin']
    assert 'blocks are now' in q['next_skill']['instructions']


def _view_after(name, *moves, **faults):
    from episode import setup
    import skills
    sc, bench, cell, tracker = setup(name, **faults)
    for skill, arg in moves:
        tracker.record(skills.run(cell, skill, arg))
        tracker.next_step()
    return decision_model.view(tracker.build(cell.gripper(), cell.tcp()))


def test_view_has_no_history_option_words_or_codes():
    v = _view_after('nominal', ('pick', 'A'), ('place', 'C'))
    text = json.dumps(v).lower()
    assert not any(w in text for w in ('pick', 'place', 'obj', '"pos"', 'duration', 'step', 'history'))
    assert v == {'instruction': 'Move the block in A to C.', 'gripper': 'open, empty',
                 'blocks_removed_from': ['A'], 'blocks_put_in': ['C'], 'blocks_in_bin': 0,
                 'found_empty': [], 'not_visited_yet': ['B']}


def test_view_while_holding():
    v = _view_after('nominal', ('pick', 'A'))
    assert v['gripper'] == 'holding a block, 39.9 mm wide' and v['not_visited_yet'] == ['B', 'C']


def test_view_repeated_empty_picks_name_the_slot_once():
    v = _view_after('slip_always', ('pick', 'A'), ('pick', 'A'))
    assert v['gripper'] == 'closed, empty' and v['found_empty'] == ['A']
    assert json.dumps(v).count('"A"') == 1


def test_view_bin_count_and_failed_slot_counts_as_not_visited():
    v = _view_after('full_bench', ('pick', 'A'), ('place', 'bin'))
    assert v['blocks_in_bin'] == 1 and v['blocks_removed_from'] == ['A'] and v['blocks_put_in'] == []
    st = {'instruction': 'x', 'gripper': {'obj': 3, 'meaning': '', 'pos': 3, 'width_mm': None},
          'slots': {'A': {'event': 'failed', 'placed': 0}, 'bin': {'event': None, 'placed': 0}}}
    assert decision_model.view(st)['not_visited_yet'] == ['A']


def test_decide_sends_the_view():
    class Stub:
        def system_one(self, state, questions):
            self.state = state
            return {'answers': {'next_skill': {'probabilities': {'done': 1.0}}}}
    decider = object.__new__(decision_model.ModelDecider)
    decider.model, decider.cuda = Stub(), False
    from episode import setup
    sc, bench, cell, tracker = setup('nominal')
    st = tracker.build(cell.gripper(), cell.tcp())
    d = decider.decide(st, tracker.options(st))
    assert json.loads(decider.model.state) == decision_model.view(st) == d.extra['model_state']


def test_parse_real_answer():
    fx = json.load(open(FIXTURE))
    d = decision_model.parse(fx['raw'], fx['options'], latency_s=27.4)
    assert d.choice == 'place:C' and d.probs['place:C'] == pytest.approx(0.594, abs=1e-3)
    assert set(d.probs) == set(fx['options'])
    assert d.last_ok_prob == pytest.approx(0.569, abs=1e-3)
    assert d.task_done_prob == pytest.approx(0.744, abs=1e-3)
    assert d.extra['confidence'] == pytest.approx(0.286, abs=1e-3) and d.extra['error'] is None


def test_parse_real_d3lite_answer():
    fx = json.load(open(FIXTURE_D3))
    d = decision_model.parse(fx['raw'], fx['options'], latency_s=0.5)
    assert d.choice == 'place:A' and d.probs['place:A'] == pytest.approx(0.521, abs=1e-3)
    assert d.last_ok_prob == pytest.approx(0.105, abs=1e-3)
    assert d.task_done_prob == pytest.approx(0.196, abs=1e-3)
    assert d.extra['usage']['input_tokens'] == 1341


def test_default_model_is_d3_lite():
    assert decision_model.MODEL == 'vllm-sr/d3-lite'


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
    decider = decision_model.ModelDecider(device=os.environ.get('UR10_MODEL_DEVICE', 'auto'))
    d = decider.decide(st, options)
    assert set(d.probs) == set(options) and d.choice in options
    assert sum(d.probs.values()) == pytest.approx(1.0, abs=0.02)
    assert 0 <= d.last_ok_prob <= 1 and 0 <= d.task_done_prob <= 1
