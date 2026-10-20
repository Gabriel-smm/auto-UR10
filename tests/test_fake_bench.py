"""fake_bench.py: picking, placing and injected faults."""

import json

import pytest

import fake_bench
from conftest import A, AWAY, B, BIN, C
from fake_gripper import OBJ_REACHED, OBJ_STOPPED, POS_MAX, POS_MIN


def test_slot_at_nearest_within_tolerance(make_bench):
    bench = make_bench()
    assert bench.slot_at(A[:3]) == 'A'
    assert bench.slot_at([A[0] + 0.015, A[1], A[2]]) == 'A'
    assert bench.slot_at([A[0] + 0.03, A[1], A[2]]) is None
    assert bench.slot_at([A[0] + 0.03, A[1], A[2]], tol=0.05) == 'A'
    assert bench.slot_at(AWAY) is None


def test_pos_for_width():
    assert fake_bench.pos_for(85) == POS_MIN
    assert fake_bench.pos_for(0) == POS_MAX
    assert fake_bench.pos_for(40) < fake_bench.pos_for(20)


def test_pick_from_full_slot(make_bench):
    bench = make_bench()
    assert bench.close(A[:3]) == (OBJ_STOPPED, fake_bench.pos_for(40))
    assert bench.held['id'] == 'a'
    assert bench.blocks()['A'] is None


def test_close_on_empty_slot(make_bench):
    bench = make_bench()
    assert bench.close(C[:3]) == (OBJ_REACHED, POS_MAX)
    assert bench.held is None


def test_close_short_of_the_block_does_not_pick(make_bench):
    bench = make_bench()
    assert bench.close(A[:3], target=50) == (OBJ_REACHED, 50)
    assert bench.blocks()['A']['id'] == 'a'


def test_drop_in_bin(make_bench):
    bench = make_bench()
    bench.close(A[:3])
    assert bench.open(BIN[:3]) == (OBJ_REACHED, POS_MIN)
    assert bench.held is None
    assert [b['id'] for b in bench.binned] == ['a']
    assert bench.blocks()['bin'] is None
    assert bench.events[-1]['outcome'] == 'binned'


def test_place_in_empty_slot(make_bench):
    bench = make_bench()
    bench.close(A[:3])
    bench.open(C[:3])
    assert bench.blocks()['C']['id'] == 'a'
    assert bench.events[-1]['outcome'] == 'placed'
    # and it can be picked again from there
    assert bench.close(C[:3])[0] == OBJ_STOPPED


def test_open_on_occupied_slot_or_away_drops(make_bench):
    bench = make_bench()
    bench.close(A[:3])
    bench.open(B[:3])
    assert bench.blocks()['B']['id'] == 'b'
    assert [b['id'] for b in bench.lost] == ['a']
    bench.close(B[:3])
    bench.open(AWAY)
    assert [b['id'] for b in bench.lost] == ['a', 'b']


def test_slip_after_leaving_pick_slot(make_bench):
    bench = make_bench(p_slip=1)
    assert bench.close(A[:3])[0] == OBJ_STOPPED
    assert bench.update(A[:3]) is None          # still at the slot: holding
    assert bench.update(AWAY) == (OBJ_REACHED, POS_MAX)
    assert bench.held is None
    assert [e['fault'] for e in bench.injected] == ['slip']
    bench.open(C[:3])
    assert bench.blocks()['C'] is None


def test_miss(make_bench):
    bench = make_bench(p_miss=1)
    assert bench.close(A[:3]) == (OBJ_REACHED, POS_MAX)
    assert bench.blocks()['A']['id'] == 'a'
    assert [e['fault'] for e in bench.injected] == ['miss']


def test_ghost_block(make_bench):
    bench = make_bench(ghost_block=1)
    obj, pos = bench.close(C[:3])
    assert obj == OBJ_STOPPED and pos == fake_bench.pos_for(fake_bench.GHOST_WIDTH_MM)
    assert bench.held is None and bench.ghost
    assert [e['fault'] for e in bench.injected] == ['ghost']
    bench.open(B[:3])
    assert bench.blocks()['B']['id'] == 'b' and not bench.lost


def test_width_noise_bounded(make_bench):
    for seed in range(20):
        bench = make_bench(seed, width_noise_mm=2)
        _, pos = bench.close(A[:3])
        assert fake_bench.pos_for(42) <= pos <= fake_bench.pos_for(38)


def run(bench):
    """A fixed sequence of picks and places; returns the events without timestamps."""
    for pick, place in [(A, BIN), (B, C), (C, A), (A, BIN)]:
        bench.close(pick[:3])
        bench.update(AWAY)
        bench.open(place[:3])
    return [{k: v for k, v in e.items() if k != 't'} for e in bench.events]


def test_same_seed_same_run(make_bench):
    faults = {'p_slip': 0.4, 'p_miss': 0.4, 'width_noise_mm': 3, 'ghost_block': 0.5}
    assert run(make_bench(7, **faults)) == run(make_bench(7, **faults))
    assert run(make_bench(7, **faults)) != run(make_bench(8, **faults))


def test_log_file(tmp_path, make_bench):
    from conftest import scenario
    path = tmp_path / 'logs' / 'run.jsonl'
    bench = fake_bench.Bench(scenario(3, p_miss=1), log_path=str(path))
    bench.close(A[:3])
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [e['event'] for e in lines] == ['start', 'close']
    assert all(e['scenario'] == 'test' and e['seed'] == 3 for e in lines)
    assert lines[0]['faults']['p_miss'] == 1 and lines[1]['fault'] == 'miss'
    assert bench.log_info()['injected'] == bench.injected


@pytest.mark.parametrize('data, message', [
    ({'slots': {'A': {}}}, 'no pose'),
    ({'slots': {'A': {'pose': A, 'block': {'id': 'x', 'width_mm': 90}}}}, 'width_mm'),
    ({'slots': {'bin': {'pose': BIN, 'bin': True, 'block': {'id': 'x', 'width_mm': 9}}}}, 'bin'),
    ({'faults': {'p_slp': 1}}, 'unknown faults'),
    ({'faults': {'p_slip': 2}}, 'p_slip'),
])
def test_bad_scenarios_are_rejected(data, message):
    with pytest.raises(ValueError, match=message):
        fake_bench.parse_scenario(data)
