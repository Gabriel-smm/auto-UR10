"""Replay a run_task.py episode from its log, in the same panels, without a robot.

    python scripts/replay.py logs/20261020-202116-full_bench-rules.jsonl
    python scripts/replay.py LOG --all        # print every step without waiting

Keys: Enter or space next step, q quit.
"""

import argparse
import json
import sys

from rich.console import Console

import panel
from run_task import Keys

# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def load(path):
    """(start, steps, end) from a run_task log; end may be None if the run was cut short."""
    entries = [json.loads(line) for line in open(path) if line.strip()]
    start = next(e for e in entries if e['type'] == 'start')
    steps = [e for e in entries if e['type'] == 'step']
    end = next((e for e in entries if e['type'] == 'end'), None)
    return start, steps, end


def show_step(ui, start, e):
    ui.rule()
    ui.print(panel.header(start, e['step']))
    ui.print(panel.state_panel(e['state']))
    ui.print(panel.decision_panel(e['decision'], start['threshold'], e['abstained'], e['executed']))
    op = e['operator']
    ui.print(f'operator: {op["action"]}' + (f' -> {op["choice"]}' if op.get('choice') else ''),
             style='bold', markup=False, highlight=False)
    ui.print(panel.plan_panel(e['plan']))
    ui.print(panel.result_panel(e['result']))
    if 'bench' in e:
        ui.print(panel.bench_panel(e['bench'], e['injected']))


def main():
    parser = argparse.ArgumentParser(description='Replay a run_task.py log.')
    parser.add_argument('log')
    parser.add_argument('--all', action='store_true', help='print every step without waiting')
    args = parser.parse_args()

    ui = Console()
    start, steps, end = load(args.log)
    ui.print(f'{start["run_id"]}: {start["instruction"]}', style='bold', markup=False)
    with Keys(not args.all) as keys:
        for e in steps:
            show_step(ui, start, e)
            if keys.active:
                ui.print('[Enter] next  [q] quit', markup=False, highlight=False, style='dim')
                if keys.get() == 'q':
                    sys.exit(0)
    if end:
        extra = f'   match {end["match"]}' if 'match' in end else ''
        ui.print(f'outcome: {end["outcome"]}   steps {end["steps"]}{extra}', style='bold', markup=False)


if __name__ == '__main__':
    main()
