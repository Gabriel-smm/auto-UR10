"""robot.py: --scenario is simulator-only and gives the fake gripper a bench."""

import argparse
import json
import os

import pytest

import fake_gripper
import robot

SCENARIO = os.path.join(os.path.dirname(__file__), '..', 'scenarios', 'nominal.json')


def parse(argv, env=None):
    parser = argparse.ArgumentParser()
    robot.add_args(parser)
    args = parser.parse_args(argv)
    return robot.select(parser, args, env or {}), args


def test_scenario_needs_sim():
    with pytest.raises(SystemExit):
        parse(['--scenario', SCENARIO])
    with pytest.raises(SystemExit):
        parse([], {robot.ENV_SCENARIO: SCENARIO})


def test_no_scenario_no_bench():
    (ip, sim), args = parse(['--sim'])
    assert robot.gripper(sim, args) is fake_gripper
    assert fake_gripper._bench is None


def test_scenario_sets_bench_and_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(robot, 'LOG_DIR', str(tmp_path))
    (ip, sim), args = parse(['--sim'], {robot.ENV_SCENARIO: SCENARIO})
    try:
        robot.gripper(sim, args, env={robot.ENV_SEED: '5'})
        bench = fake_gripper._bench
        assert (bench.name, bench.seed) == ('nominal', 5)
        assert 'SCENARIO: nominal  seed 5' in capsys.readouterr().out
        [log] = tmp_path.iterdir()
        start = json.loads(log.read_text().splitlines()[0])
        assert (start['event'], start['scenario'], start['seed']) == ('start', 'nominal', 5)
    finally:
        fake_gripper.set_bench(None)


def test_real_robot_gets_real_gripper():
    (ip, sim), args = parse([])
    assert ip == robot.REAL_IP and robot.gripper(sim, args).__name__ == 'gripper'
