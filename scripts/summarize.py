"""Summarize run_task.py logs per decider and model.

    python scripts/summarize.py logs/suite-20261020-203000.json
    python scripts/summarize.py logs/                      # every run_task log in the folder
    python scripts/summarize.py logs/a.jsonl logs/b.jsonl

Per decider/model: episodes, outcomes, success rate, decision accuracy,
abstentions (right or wrong), mean steps, decision latency (median, p95) and
peak VRAM. Per injected fault type: how often the next decision doubted the
last skill (detected: last_ok < 0.5), closed the gripper at the same slot again (retried),
and how often the episode then ended in a wrong 'done'.

Right and wrong are judged against the bench truth before each step (the
simulator logs it), with what an ideal decider would do:
    holding a block           place it where 'expected' wants it
    holding nothing           pick a block that is not yet where it should be,
                              or 'done' if every block is
What the decider cannot know also counts as right: picking a slot the state
shows as never gripped from and found empty fewer than twice (it may hold a
block, or a pick may have missed), and placing when the state says holding
but nothing is (a ghost block).
A step where none of the offered options is right (for example after a ghost
block, when the state says holding but nothing is held) is not scored.
"""

import argparse
import glob
import json
import os
import statistics
from collections import defaultdict

from rich.console import Console
from rich.table import Table

from decision import next_primitives

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def run_logs(paths):
    """run_task log paths from suite files, folders and .jsonl files."""
    out = []
    for path in paths:
        if os.path.isdir(path):
            out += sorted(glob.glob(os.path.join(path, '*.jsonl')))
        elif path.endswith('.json'):
            out += [r['log'] for r in json.load(open(path))['runs'] if r.get('log')]
        else:
            out.append(path)
    episodes = []
    for path in out:
        entries = [json.loads(line) for line in open(path) if line.strip()]
        if entries and entries[0].get('type') == 'start' and 'decider' in entries[0]:
            episodes.append(entries)        # bench logs from fake_bench have no 'type'
    return episodes

# ---------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------


def right_choices(bench, expected, state=None):
    """Options an ideal decider would take, given the bench truth (and what the state lets it know).

    The ideal goals (pick:X, place:Y, done) become the primitives that make
    progress towards them from where the arm and gripper are
    (decision.next_primitives). Without a state, or for a log written before
    the primitives, the goals themselves are returned.
    """
    goals = right_goals(bench, expected, state)
    if goals is None or not state or 'tcp_level' not in state:
        return goals
    return {p for goal in goals for p in next_primitives(goal, state)}


def right_goals(bench, expected, state=None):
    """Goals an ideal decider would pursue, given the bench truth."""
    if bench is None or expected is None:
        return None

    def target(block_id):
        for slot, want in expected['slots'].items():
            if want == block_id:
                return slot
        return 'bin' if block_id in expected['binned'] else None

    if bench['held']:
        t = target(bench['held']['id'])
        return {f'place:{t}'} if t else set()
    if state and state['holding']:             # ghost: the gripper says holding, nothing is
        return {f'place:{s}' for s in state['slots']} | {'done'}
    misplaced = {slot for slot, b in bench['slots'].items() if b and target(b['id']) != slot}
    right = {f'pick:{s}' for s in misplaced} or {'done'}
    if state:
        right |= {f'pick:{s}' for s, c in state['slots'].items()
                  if s != 'bin' and not c['gripped'] and c['empty'] < 2}
    return right


RETRY_WINDOW = 8        # steps after a fault in which a close at the same slot counts as a retry


def judge(episode):
    """Per-step judgements and fault reactions for one episode."""
    start, steps = episode[0], [e for e in episode if e['type'] == 'step']
    end = next((e for e in episode if e['type'] == 'end'), {'outcome': 'incomplete', 'steps': len(steps)})
    before = start.get('initial_bench')
    judged = []
    for e in steps:
        right = right_choices(before, start.get('expected'), e['state'])
        scorable = right is not None and bool(right & set(e['options']))
        judged.append({'step': e, 'right': right, 'scorable': scorable,
                       'correct': scorable and e['decision']['choice'] in right})
        before = e.get('bench', before)

    faults = []
    wrong_done = end['outcome'] == 'fail' and steps and steps[-1]['executed'] == 'done'
    for i, e in enumerate(steps):
        for f in e.get('injected') or []:
            later = steps[i + 1:i + 1 + RETRY_WINDOW]
            nxt = later[0]['decision'] if later else None
            faults.append({'fault': f['fault'],
                           'detected': bool(nxt and nxt['last_ok_prob'] is not None and nxt['last_ok_prob'] < 0.5),
                           'retried': any(s['executed'] == 'close' and s['state'].get('tcp_at') == f['slot']
                                          or s['executed'] == f'pick:{f["slot"]}' for s in later),
                           'wrong_done': bool(wrong_done)})
    return start, end, judged, faults

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def pct(n, d):
    return f'{100 * n / d:.0f}% ({n}/{d})' if d else '—'


def summarize(episodes):
    groups = defaultdict(lambda: {'episodes': 0, 'outcomes': defaultdict(int), 'steps': [], 'latency': [],
                                  'vram': [], 'scored': 0, 'correct': 0, 'abst_right': 0, 'abst_wrong': 0,
                                  'abst_unscored': 0, 'faults': defaultdict(lambda: defaultdict(int))})
    for ep in episodes:
        start, end, judged, faults = judge(ep)
        g = groups[(start['decider'], start.get('model') or '—')]
        g['episodes'] += 1
        g['outcomes'][end['outcome']] += 1
        g['steps'].append(end['steps'])
        for j in judged:
            d = j['step']['decision']
            g['latency'].append(d['latency_s'])
            if d.get('vram_peak_mb') is not None:
                g['vram'].append(d['vram_peak_mb'])
            g['scored'] += j['scorable']
            g['correct'] += j['correct']
            if j['step']['abstained']:
                if not j['scorable']:
                    g['abst_unscored'] += 1
                elif j['correct']:
                    g['abst_wrong'] += 1        # it would have been right: abstaining was a mistake
                else:
                    g['abst_right'] += 1
        for f in faults:
            c = g['faults'][f['fault']]
            c['n'] += 1
            c['detected'] += f['detected']
            c['retried'] += f['retried']
            c['wrong_done'] += f['wrong_done']
    return groups


def latency(values):
    if not values:
        return '—'
    p95 = statistics.quantiles(values, n=20)[-1] if len(values) > 1 else values[0]
    return f'{statistics.median(values):.3f} / {p95:.3f} s'


def show(groups, ui=None):
    ui = ui or Console()
    table = Table(title='Episodes per decider')
    for col in ('decider', 'model', 'episodes', 'success', 'outcomes', 'step accuracy',
                'abstentions right / wrong / unscored', 'mean steps', 'latency median / p95', 'VRAM peak'):
        table.add_column(col)
    for (decider, model), g in sorted(groups.items()):
        outcomes = ', '.join(f'{k} {v}' for k, v in sorted(g['outcomes'].items()))
        table.add_row(decider, model, str(g['episodes']), pct(g['outcomes']['success'], g['episodes']), outcomes,
                      pct(g['correct'], g['scored']),
                      f'{g["abst_right"]} / {g["abst_wrong"]} / {g["abst_unscored"]}',
                      f'{statistics.mean(g["steps"]):.1f}' if g['steps'] else '—', latency(g['latency']),
                      f'{max(g["vram"]):.0f} MB' if g['vram'] else '—')
    ui.print(table)

    faults = Table(title='Reaction to injected faults (next decision)')
    for col in ('decider', 'model', 'fault', 'injected', 'detected (last_ok < 0.5)', 'retried same slot',
                'episode ended in a wrong done'):
        faults.add_column(col)
    for (decider, model), g in sorted(groups.items()):
        for fault, c in sorted(g['faults'].items()):
            faults.add_row(decider, model, fault, str(c['n']), pct(c['detected'], c['n']),
                           pct(c['retried'], c['n']), pct(c['wrong_done'], c['n']))
    ui.print(faults)


def main():
    parser = argparse.ArgumentParser(description='Summarize run_task.py logs.')
    parser.add_argument('paths', nargs='+', help='suite .json files, folders, or run_task .jsonl logs')
    args = parser.parse_args()
    episodes = run_logs(args.paths)
    if not episodes:
        raise SystemExit('No run_task logs found.')
    show(summarize(episodes))


if __name__ == '__main__':
    main()
