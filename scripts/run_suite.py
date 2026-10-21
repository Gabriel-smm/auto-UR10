"""Run every scenario, under several seeds, headless in the simulator.

    python scripts/run_suite.py --decider rules --seeds 1 2 3
    python scripts/run_suite.py --decider model --model vllm-sr/Decision-2.0-Sol-2B --device cpu
    python scripts/run_suite.py --decider rules --backend ursim --scenarios 'scenarios/slip_*.json'

Each episode is run_task.py --sim --mode headless with the bench seed set,
and writes its own log. The decider (and the model) is loaded once. The list
of logs goes to logs/suite-<YYYYmmdd-HHMMSS>.json, for summarize.py.
"""

import argparse
import glob
import json
import os
import time

import robot
import run_task

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCENARIOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scenarios', '*.json')
SEEDS = [1, 2, 3]

# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description='Run all scenarios headless in the simulator.')
    p.add_argument('--decider', choices=('rules', 'model'), default='rules')
    p.add_argument('--model', default='vllm-sr/Decision-2.0-Sol-2B')
    p.add_argument('--device', choices=('auto', 'cuda', 'cpu'), default='auto')
    p.add_argument('--bf16-resident', action='store_true')
    p.add_argument('--seeds', type=int, nargs='+', default=SEEDS)
    p.add_argument('--backend', choices=('fake', 'ursim'), default='fake')
    p.add_argument('--scenarios', default=SCENARIOS, help='glob of scenario files')
    p.add_argument('--threshold', type=float, default=run_task.THRESHOLD)
    p.add_argument('--max-steps', type=int, default=run_task.MAX_STEPS)
    p.add_argument('--log-dir', default=run_task.LOG_DIR)
    args = p.parse_args()

    paths = sorted(glob.glob(args.scenarios))
    if not paths:
        p.error(f'no scenarios match {args.scenarios}')

    base = ['--sim', '--mode', 'headless', '--backend', args.backend, '--decider', args.decider,
            '--model', args.model, '--device', args.device, '--threshold', str(args.threshold),
            '--max-steps', str(args.max_steps), '--log-dir', args.log_dir]
    if args.bf16_resident:
        base.append('--bf16-resident')
    parser = run_task.make_parser()
    decider = run_task.make_decider(parser.parse_args(base))

    runs, t0 = [], time.time()
    print(f'{len(paths)} scenarios x {len(args.seeds)} seeds, decider {args.decider}, backend {args.backend}')
    for path in paths:
        for seed in args.seeds:
            ep = parser.parse_args(base + ['--scenario', path, '--seed', str(seed)])
            ip, sim = robot.select(parser, ep, env={})
            run_task.check_args(parser, ep, sim)
            try:
                end = run_task.run_episode(ep, ip, sim, decider)
                runs.append({'scenario': os.path.splitext(os.path.basename(path))[0], 'seed': seed,
                             'outcome': end['outcome'], 'steps': end['steps'], 'log': end['log']})
            except Exception as e:      # one broken episode does not stop the suite
                runs.append({'scenario': os.path.basename(path), 'seed': seed, 'outcome': 'error',
                             'error': repr(e)})
                print(f'{path} seed {seed}: error {e!r}')

    os.makedirs(args.log_dir, exist_ok=True)
    out = os.path.join(args.log_dir, f'suite-{time.strftime("%Y%m%d-%H%M%S")}.json')
    with open(out, 'w') as f:
        json.dump({'decider': args.decider, 'model': args.model if args.decider == 'model' else None,
                   'backend': args.backend, 'seeds': args.seeds, 'duration_s': round(time.time() - t0, 1),
                   'runs': runs}, f, indent=1)
    ok = sum(r['outcome'] == 'success' for r in runs)
    print(f'{ok}/{len(runs)} success in {time.time() - t0:.0f} s; suite file {os.path.relpath(out)}')
    print(f'summary: python scripts/summarize.py {os.path.relpath(out)}')


if __name__ == '__main__':
    main()
