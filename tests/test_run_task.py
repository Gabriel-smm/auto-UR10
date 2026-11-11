"""run_task.py: argument rules, headless episodes on the fake backend, and the log."""

import json
import os

import pytest

import robot
import run_task

SCEN = os.path.join(os.path.dirname(__file__), '..', 'scenarios')


def parse(argv):
    parser = run_task.make_parser()
    args = parser.parse_args(argv)
    ip, sim = robot.select(parser, args, env={})
    run_task.check_args(parser, args, sim)
    return args, ip, sim


@pytest.mark.parametrize('argv, message', [
    (['--instruction', 'x', '--mode', 'auto'], 'only for the simulator'),
    (['--instruction', 'x', '--mode', 'headless'], 'only for the simulator'),
    (['--mode', 'step'], 'needs --instruction'),
    (['--instruction', 'x', '--speed', '0.2'], 'limit on the real robot'),
    (['--instruction', 'x', '--backend', 'fake'], 'only for the simulator'),
    (['--sim'], 'needs --scenario'),
])
def test_rejected(argv, message, capsys):
    with pytest.raises(SystemExit):
        parse(argv)
    assert message in capsys.readouterr().err


def episode(tmp_path, name, *extra):
    args, ip, sim = parse(['--sim', '--backend', 'fake', '--scenario', os.path.join(SCEN, f'{name}.json'),
                           '--mode', 'headless', '--log-dir', str(tmp_path), *extra])
    end = run_task.run_episode(args, ip, sim)
    lines = [json.loads(line) for line in open(end['log'])]
    return end, lines


def test_headless_rules_success_and_log(tmp_path, monkeypatch):
    monkeypatch.setattr(robot, 'LOG_DIR', str(tmp_path / 'bench'))
    end, lines = episode(tmp_path, 'nominal')
    assert end['outcome'] == 'success' and end['match']
    start, steps, last = lines[0], lines[1:-1], lines[-1]
    assert start['type'] == 'start' and start['target'] == 'SIMULATOR' and start['scenario'] == 'nominal'
    assert start['instruction'] == 'Move the block in A to C.' and start['seed'] == 1
    assert [s['decision']['choice'] for s in steps] == ['move:A', 'down', 'close', 'up', 'move:C', 'down',
                                                        'open', 'done']
    assert all(s['operator']['action'] == 'auto' for s in steps)
    s2 = steps[2]
    assert s2['plan']['ok'] and s2['result']['ok'] and s2['bench']['held']['id'] == 'wide1'
    s0 = steps[0]
    assert 'bench' not in json.dumps(s0['state'])
    assert last['type'] == 'end' and last['outcome'] == 'success' and last['final_bench']['slots']['C']['id'] == 'wide1'


def test_injected_faults_are_logged_per_step(tmp_path, monkeypatch):
    monkeypatch.setattr(robot, 'LOG_DIR', str(tmp_path / 'bench'))
    end, lines = episode(tmp_path, 'slip_always')
    steps = [e for e in lines if e['type'] == 'step']
    first_up = next(s for s in steps if s['executed'] == 'up')
    assert [e['fault'] for e in first_up['injected']] == ['slip']
    assert end['outcome'] == 'fail' and not end['match']


def test_abstention_ends_headless(tmp_path, monkeypatch):
    monkeypatch.setattr(robot, 'LOG_DIR', str(tmp_path / 'bench'))
    end, lines = episode(tmp_path, 'nominal', '--threshold', '1.01')
    assert end['outcome'] == 'abstained' and end['steps'] == 1
    step = lines[1]
    assert step['abstained'] and step['operator']['action'] == 'abstain' and step['result'] is None


def test_max_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(robot, 'LOG_DIR', str(tmp_path / 'bench'))
    end, _ = episode(tmp_path, 'full_bench', '--max-steps', '2')
    assert end['outcome'] == 'max_steps' and end['steps'] == 2


def test_seed_override(tmp_path, monkeypatch):
    monkeypatch.setattr(robot, 'LOG_DIR', str(tmp_path / 'bench'))
    end, lines = episode(tmp_path, 'nominal', '--seed', '9')
    assert lines[0]['seed'] == 9
