"""replay.py, run_suite.py and summarize.py on headless fake-backend episodes."""

import io
import json
import os
import subprocess
import sys

from rich.console import Console

import replay
import summarize

REPO = os.path.join(os.path.dirname(__file__), '..')


def suite(tmp_path, pattern, seeds=('1',)):
    subprocess.run([sys.executable, os.path.join(REPO, 'scripts', 'run_suite.py'), '--decider', 'rules',
                    '--scenarios', os.path.join(REPO, 'scenarios', pattern), '--seeds', *seeds,
                    '--log-dir', str(tmp_path)], check=True, capture_output=True, cwd=REPO)
    [path] = tmp_path.glob('suite-*.json')
    return path


def test_suite_file_and_logs(tmp_path):
    path = suite(tmp_path, 'single_*.json', ('1', '2'))
    data = json.load(open(path))
    assert data['decider'] == 'rules' and len(data['runs']) == 6
    assert all(r['outcome'] == 'success' and os.path.exists(r['log']) for r in data['runs'])
    assert len({r['log'] for r in data['runs']}) == 6          # one log per episode


def test_summarize_counts(tmp_path):
    path = suite(tmp_path, 'slip_always.json')
    episodes = summarize.run_logs([str(path)])
    groups = summarize.summarize(episodes)
    g = groups[('rules', '—')]
    assert g['episodes'] == 1 and g['outcomes']['fail'] == 1
    slip = g['faults']['slip']
    assert slip['n'] >= 1 and slip['detected'] == slip['n']        # the force-100 slip shows in the status
    out = io.StringIO()
    summarize.show(groups, Console(file=out, width=200))
    assert 'slip' in out.getvalue() and 'rules' in out.getvalue()


def test_right_choices():
    bench = {'slots': {'A': {'id': 'a'}, 'B': None, 'C': None}, 'held': None, 'binned': [], 'lost': []}
    expected = {'slots': {'A': None, 'B': None, 'C': 'a'}, 'binned': []}
    assert summarize.right_choices(bench, expected) == {'pick:A'}
    held = dict(bench, slots={'A': None, 'B': None, 'C': None}, held={'id': 'a'})
    assert summarize.right_choices(held, expected) == {'place:C'}
    done = dict(bench, slots={'A': None, 'B': None, 'C': {'id': 'a'}})
    assert summarize.right_choices(done, expected) == {'done'}


def test_replay_renders_every_step(tmp_path):
    path = suite(tmp_path, 'nominal.json')
    log = json.load(open(path))['runs'][0]['log']
    start, steps, end = replay.load(log)
    out = io.StringIO()
    ui = Console(file=out, width=120)
    for e in steps:
        replay.show_step(ui, start, e)
    text = out.getvalue()
    assert 'decision: pick:A' in text and 'BENCH TRUTH' in text and end['outcome'] == 'success'
