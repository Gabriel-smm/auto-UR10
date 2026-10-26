"""skills.py against fake_arm + fake_gripper + fake_bench: no robot, no URSim."""

import json
import os
import threading

import pytest

import fake_arm
import fake_bench
import fake_gripper as g
import skills

REPO = os.path.join(os.path.dirname(__file__), '..')
SCENARIOS = os.path.join(REPO, 'scenarios')


@pytest.fixture
def cell_for(monkeypatch):
    """cell_for(scenario name, **fault overrides) -> (cell, bench)."""
    monkeypatch.setattr(g, 'MOVE_TIME', 0)

    def make(name='nominal', slots_file=skills.SLOTS_FILE, move_time=0.0, **faults):
        sc = fake_bench.load_scenario(os.path.join(SCENARIOS, f'{name}.json'))
        sc['faults'].update(faults)
        bench = fake_bench.Bench(sc)
        poses, _ = skills.load_slots(slots_file)
        receive = fake_arm.FakeReceive(poses['home'])
        control = fake_arm.FakeControl(receive, move_time)
        g.set_bench(bench, receive.getActualTCPPose)
        s = g.connect()
        g.activate(s)
        return skills.Cell(control, receive, g, s, slots_file), bench

    yield make
    g.set_bench(None)


def test_load_slots_approach():
    poses, approach = skills.load_slots()
    assert 'approach_z' not in poses and set(poses) == {'A', 'B', 'C', 'bin', 'home'}
    assert approach['A'] == 0.10


def test_pick_plan_segments_and_preflight(cell_for):
    cell, _ = cell_for()
    plan = skills.plan(cell, 'pick', 'A')
    assert plan['ok'] and plan['gripper'] == 'close'
    kinds = [s['kind'] for s in plan['segments']]
    assert kinds == ['transit', 'descend', 'retreat']     # home is above the approach height: no lift
    assert [s['motion'] for s in plan['segments']] == ['moveJ', 'moveL', 'moveL']
    above = plan['segments'][0]['to']
    assert above[2] == pytest.approx(cell.poses['A'][2] + 0.10, abs=1e-5)
    assert len(plan['preflight']) == 3 and all(not c['problems'] for c in plan['preflight'])
    assert 'Smallest along the path' in plan['preflight'][0]['report']
    assert cell.control.moves == []                        # planning moves nothing


def test_pick_full_slot(cell_for):
    cell, bench = cell_for()
    r = skills.pick(cell, 'A')
    assert r['ok'] and r['reason'] is None
    assert r['gripper']['obj'] == 2 and r['gripper']['width_mm'] == pytest.approx(40, abs=0.5)
    assert bench.held['id'] == 'wide1'
    assert r['tcp'][2] == pytest.approx(cell.poses['A'][2] + 0.10, abs=1e-4)   # retreated
    assert set(r) == {'skill', 'args', 'ok', 'reason', 'gripper', 'tcp', 'duration_s'}


def test_pick_empty_slot(cell_for):
    cell, bench = cell_for()
    r = skills.pick(cell, 'C')
    assert r['ok'] and r['gripper'] == {'obj': 3, 'pos': g.POS_MAX, 'width_mm': None}
    assert bench.held is None


def test_place_in_bin_and_in_slot(cell_for):
    cell, bench = cell_for('full_bench')
    skills.pick(cell, 'A')
    r = skills.place(cell, 'bin')
    assert r['ok'] and r['gripper']['obj'] == 3 and r['gripper']['width_mm'] is None
    assert [b['id'] for b in bench.binned] == ['wide1']
    cell, bench = cell_for('nominal')
    skills.pick(cell, 'A')
    skills.place(cell, 'C')
    assert bench.blocks()['C']['id'] == 'wide1' and bench.blocks()['A'] is None


def test_slip_with_force_shows_in_result(cell_for):
    cell, bench = cell_for(p_slip=1)
    r = skills.pick(cell, 'A')           # the retreat leaves the slot: the block falls
    assert r['ok'] and r['gripper']['obj'] == 3 and r['gripper']['width_mm'] is None
    assert [e['fault'] for e in bench.injected] == ['slip']


def test_miss_and_ghost(cell_for):
    cell, bench = cell_for(p_miss=1)
    r = skills.pick(cell, 'A')
    assert r['ok'] and r['gripper']['obj'] == 3 and bench.blocks()['A']['id'] == 'wide1'
    cell, bench = cell_for(ghost_block=1)
    r = skills.pick(cell, 'C')
    assert r['gripper']['obj'] == 2 and r['gripper']['width_mm'] == pytest.approx(30, abs=0.5)
    assert bench.held is None


def test_preflight_refusal_moves_nothing(cell_for, tmp_path):
    poses = json.load(open(skills.SLOTS_FILE))
    poses['X'] = [0.0, -0.6, 0.1] + poses['A'][3:]          # behind the backwall
    path = tmp_path / 'slots.json'
    path.write_text(json.dumps(poses))
    cell, _ = cell_for(slots_file=str(path))
    plan = skills.plan(cell, 'pick', 'X')
    assert not plan['ok'] and 'backwall' in plan['reason']
    r = skills.execute(cell, plan)
    assert not r['ok'] and 'backwall' in r['reason']
    assert cell.control.moves == []


def test_abort_stops_the_move(cell_for):
    cell, _ = cell_for(move_time=5.0)
    abort = threading.Event()
    threading.Timer(0.1, abort.set).start()
    r = skills.pick(cell, 'A', abort)
    assert not r['ok'] and r['reason'] == 'aborted'
    assert cell.control.stops == 1 and len(cell.control.moves) == 1
    assert r['duration_s'] < 2


def test_stale_plan_refused(cell_for):
    cell, _ = cell_for()
    plan = skills.plan(cell, 'pick', 'A')
    cell.receive.pose[2] += 0.05
    r = skills.execute(cell, plan)
    assert not r['ok'] and 'plan again' in r['reason'] and cell.control.moves == []


def test_home_and_open_gripper(cell_for):
    cell, _ = cell_for()
    skills.pick(cell, 'A')
    r = skills.home(cell)
    assert r['ok'] and r['tcp'][:3] == pytest.approx(cell.poses['home'][:3], abs=1e-4)
    r = skills.open_gripper(cell)
    assert r['ok'] and r['gripper']['obj'] == 3


def test_unknown_slot():
    with pytest.raises(ValueError):
        skills._waypoints(None, 'teleport', None, [0] * 6)


def test_movej_check_catches_joint_limit():
    """A transit whose end configuration is past the shoulder limit is refused."""
    receive = fake_arm.FakeReceive([0.0, 0.5, 0.3, 0.0, 3.14, 0.0])
    control = fake_arm.FakeControl(receive)
    q_from = receive.getActualQ()
    q_bad = list(q_from)
    q_bad[1] = -0.5                         # shoulder at -29 deg, above the -51 deg limit
    problems, report = skills.check_movej(control, q_from, q_bad)
    assert any('Shoulder' in p for p in problems) and 'joint headroom' in report


# ---------------------------------------------------------------------------
# Primitives: move, down, up, open, close
# ---------------------------------------------------------------------------


def test_move_stops_above_the_slot(cell_for):
    cell, _ = cell_for()
    r = skills.move(cell, 'A')
    assert r['ok'] and r['tcp'][2] == pytest.approx(cell.poses['A'][2] + 0.10, abs=1e-4)
    assert skills.where(cell.poses, cell.approach, cell.tcp()) == ('A', 'above')


def test_down_close_up_picks(cell_for):
    cell, bench = cell_for()
    skills.move(cell, 'A')
    assert skills.down(cell)['ok']
    assert skills.where(cell.poses, cell.approach, cell.tcp()) == ('A', 'down')
    r = skills.close_gripper(cell)
    assert r['gripper']['obj'] == 2 and bench.held['id'] == 'wide1'
    assert skills.up(cell)['ok'] and skills.where(cell.poses, cell.approach, cell.tcp()) == ('A', 'above')


def test_close_above_a_slot_finds_nothing(cell_for):
    cell, bench = cell_for()
    skills.move(cell, 'A')
    r = skills.close_gripper(cell)
    assert r['gripper']['obj'] == 3 and bench.held is None and bench.blocks()['A']['id'] == 'wide1'


def test_down_and_up_refused_when_not_over_a_slot(cell_for):
    cell, _ = cell_for()                     # at home
    for skill in ('down', 'up'):
        plan = skills.plan(cell, skill)
        assert not plan['ok'] and 'not above a slot' in plan['reason'] and plan['segments'] == []
        r = skills.execute(cell, plan)
        assert not r['ok'] and cell.control.moves == []


def test_slip_happens_on_up_with_force(cell_for):
    cell, bench = cell_for(p_slip=1)
    skills.move(cell, 'A')
    skills.down(cell)
    assert skills.close_gripper(cell)['gripper']['obj'] == 2
    r = skills.up(cell)
    assert r['gripper']['obj'] == 3 and [e['fault'] for e in bench.injected] == ['slip']


def test_open_above_the_bin_bins_the_block(cell_for):
    cell, bench = cell_for()
    for step in (lambda: skills.move(cell, 'A'), lambda: skills.down(cell),
                 lambda: skills.close_gripper(cell), lambda: skills.move(cell, 'bin')):
        step()
    skills.open_gripper(cell)                # 10 cm above the bin
    assert [b['id'] for b in bench.binned] == ['wide1']


def test_open_above_a_slot_drops_the_block(cell_for):
    cell, bench = cell_for()
    skills.move(cell, 'A')
    skills.down(cell)
    skills.close_gripper(cell)
    skills.move(cell, 'C')
    skills.open_gripper(cell)                # 10 cm above C, not at its grip pose
    assert bench.blocks()['C'] is None and [b['id'] for b in bench.lost] == ['wide1']
