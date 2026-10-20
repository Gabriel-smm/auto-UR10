"""fake_gripper.py driven by a fake_bench.Bench, with a stand-in TCP pose."""

import time

import pytest

import fake_bench
import fake_gripper as g
from conftest import A, AWAY, BIN, C


@pytest.fixture
def tcp(monkeypatch):
    """Mutable TCP pose the fake gripper reads; MOVE_TIME 0 unless a test sets it."""
    monkeypatch.setattr(g, 'MOVE_TIME', 0)
    pose = list(A)
    yield pose
    g.set_bench(None)
    g.set_object(None)


@pytest.fixture
def gripper(tcp, make_bench):
    def make(**faults):
        bench = make_bench(**faults)
        g.set_bench(bench, lambda: tcp)
        s = g.connect()
        g.activate(s)
        return bench, s
    return make


def test_close_on_block(gripper):
    bench, s = gripper()
    st = g.close(s)
    assert st['obj'] == 2 and st['pos'] == fake_bench.pos_for(40)
    assert bench.held['id'] == 'a'


def test_close_on_empty_slot(gripper, tcp):
    tcp[:] = C
    _, s = gripper()
    st = g.close(s)
    assert st['obj'] == 3 and st['pos'] == g.POS_MAX


def test_pick_and_bin(gripper, tcp):
    bench, s = gripper()
    g.close(s)
    tcp[:] = BIN
    st = g.open_(s)
    assert st['obj'] == 3 and st['pos'] == g.POS_MIN
    assert [b['id'] for b in bench.binned] == ['a']


def test_silent_slip_leaves_status(gripper, tcp):
    bench, s = gripper(p_slip=1)
    held = g.close(s)
    tcp[:] = AWAY + [0, 0, 0]
    st = g.status(s)
    assert (st['obj'], st['pos']) == (held['obj'], held['pos'])
    assert bench.held is None
    assert [e['fault'] for e in bench.injected] == ['slip']


def test_slip_with_force_shows_in_status(gripper, tcp):
    bench, s = gripper(p_slip=1)
    held = g.close(s, force=100)
    assert (held['obj'], held['pos']) == (2, fake_bench.pos_for(40))
    tcp[:] = AWAY + [0, 0, 0]
    st = g.status(s)
    assert st['obj'] == 3 and st['pos'] == g.POS_MAX


def test_status_slip_shows_in_status(gripper, tcp):
    bench, s = gripper(p_slip=1, slip_signal='status')
    assert g.close(s)['obj'] == 2
    assert g.status(s)['obj'] == 2         # still over the pick slot
    tcp[:] = AWAY + [0, 0, 0]
    st = g.status(s)
    assert st['obj'] == 3 and st['pos'] == g.POS_MAX
    assert [e['fault'] for e in bench.injected] == ['slip']


def test_moving_for_move_time(gripper, monkeypatch):
    _, s = gripper()
    monkeypatch.setattr(g, 'MOVE_TIME', 0.2)
    start = time.time()
    g.write(s, g.ACT_GOTO, g.POS_CLOSED, 64, 0)
    assert g.status(s)['obj'] == g.OBJ_MOVING
    assert g.status(s)['obj'] == g.OBJ_MOVING
    st = g.wait(s, lambda st: st['obj'] != g.OBJ_MOVING, 2)
    assert st['obj'] == 2 and time.time() - start >= 0.2


def test_without_bench_object_still_decides(tcp):
    g.set_object('wide')
    g.set_seed(1)
    s = g.connect()
    g.activate(s)
    st = g.close(s)
    assert st['obj'] == 2 and abs(st['pos'] - 120) <= g.NOISE


def test_same_status_keys_as_gripper(gripper):
    _, s = gripper()
    assert set(g.status(s)) == {'act', 'goto', 'sta', 'obj', 'fault', 'pos', 'current'}
