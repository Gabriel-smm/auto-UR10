"""Run one episode: a decider chooses skills until the instruction is done.

Loop: state (state.py) -> decider -> abstention check -> plan and preflight
(skills.py) -> panel -> confirmation -> skill -> log line -> repeat. It stops
at 'done', --max-steps, an abort, an abstention in auto or headless mode, or
an error.

    python scripts/run_task.py --sim --scenario scenarios/nominal.json --decider rules
    python scripts/run_task.py --sim --scenario scenarios/nominal.json \\
        --decider model --model vllm-sr/d3-lite
    python scripts/run_task.py --sim --backend fake --scenario ... --mode headless
    python scripts/run_task.py --instruction "Move the block in A to C."   # real robot

Modes: step (default; confirm every skill), auto (simulator only; no
confirmation), headless (simulator only; no panel, log only).

Keys in step mode: Enter execute the choice, o override (choose another
option), k skip this step without moving, p pause/resume, s expand/collapse
the state, a abort. Ctrl-C at any time, also during a move, aborts: the arm
stops (stopL/stopJ) where it is and does not go home.

On the real robot only step mode is accepted, --instruction is required,
--speed is at most 0.1 m/s, and a checklist must be answered with 'ok'
before anything connects.

Log: logs/<YYYYmmdd-HHMMSS>-<scenario[-s<seed>] or real>-<decider>.jsonl, a 'start'
line, one 'step' line per step, and an 'end' line with the outcome
(success, fail, abstained, aborted, max_steps, error).
"""

import argparse
import contextlib
import json
import os
import select
import subprocess
import sys
import termios
import threading
import time
import tty

import decision_model
import robot
import skills
import state as state_mod
from decision import split

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

THRESHOLD = 0.7
MAX_STEPS = 20
REAL_MAX_SPEED = 0.1    # m/s, highest --speed accepted on the real robot
LOG_DIR = robot.LOG_DIR
CHECKLIST = [
    'The emergency stop is within reach, and I will keep a hand on it.',
    'The working area around the arm and the bench is clear of people and objects.',
    f'Speed is reduced: --speed at most {REAL_MAX_SPEED} m/s.',
    'No PolyScope program is running.',
]

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------


def make_parser():
    p = argparse.ArgumentParser(description='Run one decision episode.')
    robot.add_args(p)
    p.add_argument('--backend', choices=('ursim', 'fake'), default='ursim',
                   help='simulator only: URSim, or fake_arm.py (no URSim, instant moves)')
    p.add_argument('--decider', choices=('rules', 'model'), default='rules')
    p.add_argument('--model', default=decision_model.MODEL)
    p.add_argument('--device', choices=('auto', 'cuda', 'cpu'), default='auto')
    p.add_argument('--bf16-resident', action='store_true')
    p.add_argument('--instruction', help='task text; default: the scenario\'s instruction')
    p.add_argument('--mode', choices=('step', 'auto', 'headless'), default='step')
    p.add_argument('--threshold', type=float, default=THRESHOLD)
    p.add_argument('--max-steps', type=int, default=MAX_STEPS)
    p.add_argument('--speed', type=float, default=skills.SPEED, help='moveL speed, m/s')
    p.add_argument('--seed', type=int, help='simulator: bench seed (overrides the scenario)')
    p.add_argument('--log-dir', default=LOG_DIR)
    return p


def check_args(parser, args, sim):
    if not sim:
        if args.mode != 'step':
            parser.error(f'--mode {args.mode} is only for the simulator: on the real robot every skill '
                         'is confirmed (--mode step)')
        if not args.instruction:
            parser.error('the real robot needs --instruction')
        if args.backend != 'ursim':
            parser.error('--backend fake is only for the simulator')
        if args.speed > REAL_MAX_SPEED:
            parser.error(f'--speed {args.speed} is above {REAL_MAX_SPEED} m/s, the limit on the real robot')
    elif not args.scenario:
        parser.error('the simulator needs --scenario (the bench to run on)')

# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


class Keys:
    """Single-key input in cbreak mode (Ctrl-C still interrupts). Inactive without a terminal."""

    def __init__(self, active):
        self.active = active and sys.stdin.isatty()
        self.saved = None

    def __enter__(self):
        if self.active:
            self.saved = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *exc):
        if self.saved:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.saved)

    def get(self, timeout=None):
        """One key, or None after timeout seconds (None: wait)."""
        if not self.active:
            return None
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if ready else None

    def watch_abort(self, abort, stop):
        """Thread body: set abort on 'a' until stop is set."""
        while not stop.is_set() and not abort.is_set():
            if not self.active:
                stop.wait(0.05)
            elif self.get(0.05) == 'a':
                abort.set()

# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------


class Log:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, entry):
        with open(self.path, 'a') as f:
            f.write(json.dumps(entry, default=str) + '\n')


def git_commit():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip() or None
    except OSError:
        return None


def bench_truth(bench):
    return {'slots': bench.blocks(), 'held': bench.held, 'binned': [b['id'] for b in bench.binned],
            'lost': [b['id'] for b in bench.lost]}


def matches(bench, expected):
    """Does the bench match the scenario's expected end state?"""
    slots = {n: (b or {}).get('id') for n, b in bench.blocks().items() if n in expected['slots']}
    return slots == expected['slots'] and sorted(b['id'] for b in bench.binned) == sorted(expected['binned'])

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def make_decider(args):
    if args.decider == 'rules':
        from decision_rules import RulesDecider
        return RulesDecider()
    from decision_model import ModelDecider
    return ModelDecider(args.model, args.device, args.bf16_resident)


def connect(args, ip, sim):
    """(control, receive, g, s, bench) for the target."""
    if sim and args.backend == 'fake':
        import fake_arm
        poses, _ = skills.load_slots()
        receive = fake_arm.FakeReceive(poses['home'])
        control = fake_arm.FakeControl(receive)
    else:
        from rtde_control import RTDEControlInterface
        from rtde_receive import RTDEReceiveInterface
        receive = RTDEReceiveInterface(ip)
        control = RTDEControlInterface(ip)
    env = dict(os.environ)
    if args.seed is not None:
        env[robot.ENV_SEED] = str(args.seed)
    g = robot.gripper(sim, args, env=env, pose_fn=receive.getActualTCPPose,
                      log_dir=os.path.join(args.log_dir, 'bench'))
    if sim and args.backend == 'fake':
        g.MOVE_TIME = 0
    return control, receive, g, g.connect(), getattr(g, '_bench', None) if sim else None

# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------


def choose_override(ui, keys, options):
    ui.print('override: ' + '   '.join(f'[{i}] {o}' for i, o in enumerate(options, 1)) + '   (other key: cancel)', markup=False, highlight=False)
    key = keys.get()
    if key and key.isdigit() and 1 <= int(key) <= len(options):
        return options[int(key) - 1]
    return None


def confirm(ui, keys, cell, st, options, decision, plan, threshold, abstained, show):
    """Step mode: returns (action, executed option, plan). action: exec, override, skip, abort."""
    executed, expanded = decision.choice, False
    while True:
        prompt = ('[Enter] execute  [o] override  [k] skip  [p] pause  [s] state  [a] abort'
                  + ('   ABSTAINED: your call' if abstained else ''))
        ui.print(prompt, style='bold yellow' if abstained else 'bold', markup=False, highlight=False)
        key = keys.get()
        if key in ('\n', '\r'):
            return ('exec' if executed == decision.choice else 'override'), executed, plan
        if key == 'k':
            return 'skip', None, None
        if key == 'a':
            return 'abort', None, None
        if key == 's':
            expanded = not expanded
            show(st, expanded, executed, plan)
        elif key == 'p':
            ui.print('paused: p to resume', style='bold', markup=False, highlight=False)
            while keys.get() != 'p':
                pass
        elif key == 'o':
            picked = choose_override(ui, keys, options)
            if picked:
                executed = picked
                plan = None if picked == 'done' else skills.plan(cell, *split(picked))
                show(st, expanded, executed, plan)


def run_episode(args, ip, sim, decider=None, ui=None, keys=None):
    """Run one episode; returns the 'end' log entry."""
    import fake_bench
    import panel
    from rich.console import Console

    headless = args.mode == 'headless'
    ui = ui or Console(quiet=headless)
    keys = keys or Keys(args.mode != 'headless')
    scenario = fake_bench.load_scenario(args.scenario) if sim else None
    instruction = args.instruction or scenario['instruction']
    target = 'SIMULATOR' if sim else 'REAL ROBOT'
    name = f'{scenario["name"]}-s{args.seed}' if sim and args.seed is not None else \
        (scenario['name'] if sim else 'real')
    run_id = f'{time.strftime("%Y%m%d-%H%M%S")}-{name}-{args.decider}'
    n = 1
    while os.path.exists(os.path.join(args.log_dir, f'{run_id}.jsonl')):
        n += 1
        run_id = f'{time.strftime("%Y%m%d-%H%M%S")}-{name}-{args.decider}-{n}'
    log = Log(os.path.join(args.log_dir, f'{run_id}.jsonl'))

    if not sim:
        ui.print(f'TARGET: REAL ROBOT ({ip})', style='bold white on red', markup=False, highlight=False)
        ui.print('Before the first movement, confirm:', style='bold', markup=False, highlight=False)
        for item in CHECKLIST:
            ui.print(f'  [ ] {item}', markup=False, highlight=False)
        if input('Type ok to continue: ').strip() != 'ok':
            raise SystemExit('Checklist not confirmed: nothing connected, nothing moved.')

    decider = decider or make_decider(args)
    control = receive = g = s = bench = None
    try:
        control, receive, g, s, bench = connect(args, ip, sim)
    except BaseException:
        for close in (lambda: control.stopScript(), lambda: receive.disconnect()):
            with contextlib.suppress(Exception):
                close()
        raise
    meta = {'type': 'start', 'run_id': run_id, 'target': target, 'ip': ip, 'backend': args.backend if sim else 'robot',
            'scenario': scenario['name'] if sim else None, 'seed': bench.seed if bench else None,
            'faults': bench.faults if bench else None, 'instruction': instruction,
            'expected': scenario['expected'] if sim else None, 'decider': args.decider,
            'model': args.model if args.decider == 'model' else None,
            'device': getattr(decider, 'device', None), 'threshold': args.threshold, 'mode': args.mode,
            'max_steps': args.max_steps, 'speed': args.speed, 'git_commit': git_commit(),
            'bench_log': bench.log_path if bench else None,
            'initial_bench': bench_truth(bench) if bench else None}
    log.write(meta)
    end = {'type': 'end', 'run_id': run_id, 'outcome': None, 'steps': 0}
    abort = threading.Event()
    try:
        with keys:
            st0 = g.status(s)
            if st0 is None:
                raise SystemExit('Gripper not answering: check its plug, cart power and the USB cable')
            if st0['sta'] != g.STA_ACTIVATED:
                if not sim:
                    ui.print('The gripper is not activated: activation opens and closes the fingers fully. '
                             'Enter to activate, any other key to stop.', style='bold yellow')
                    if keys.get() not in ('\n', '\r'):
                        raise SystemExit('Gripper not activated: stopped.')
                g.activate(s)
            cell = skills.Cell(control, receive, g, s, speed=args.speed)
            poses, approach = skills.load_slots()
            tracker = state_mod.Tracker(instruction, poses, approach)
            n_injected = len(bench.injected) if bench else 0

            for step in range(args.max_steps):
                tracker.step = step
                end['steps'] = step + 1
                st = tracker.build(cell.gripper(), cell.tcp())
                options = tracker.options(st)
                decision = decider.decide(st, options)
                p_choice = decision.probs.get(decision.choice, 0.0)
                abstained = p_choice < args.threshold
                plan = None if decision.choice == 'done' else skills.plan(cell, *split(decision.choice))

                def show(st_, expanded, executed, plan_):
                    ui.rule()
                    ui.print(panel.header(meta, step))
                    ui.print(panel.state_panel(st_, expanded))
                    ui.print(panel.decision_panel(decision.to_dict(), args.threshold, abstained, executed))
                    ui.print(panel.plan_panel(plan_))
                show(st, False, decision.choice, plan)

                entry = {'type': 'step', 'run_id': run_id, 'step': step, 'state': st, 'options': options,
                         'questions': decision.questions, 'decision': decision.to_dict(),
                         'abstained': abstained, 'vram_peak_mb': decision.vram_peak_mb}
                if args.mode == 'step':
                    action, executed, plan = confirm(ui, keys, cell, st, options, decision, plan,
                                                     args.threshold, abstained, show)
                elif abstained:
                    action, executed, plan = 'abstain', None, None
                else:
                    action, executed = 'auto', decision.choice
                    key = keys.get(0)
                    if key == 'p':
                        ui.print('paused: p to resume', style='bold', markup=False, highlight=False)
                        while keys.get() != 'p':
                            pass
                    elif key == 'a':
                        action, executed, plan = 'abort', None, None
                entry['operator'] = {'action': action, 'choice': executed if action == 'override' else None}
                entry['executed'] = executed
                entry['plan'] = plan
                entry['preflight'] = plan['preflight'] if plan else None

                result = None
                if executed and executed != 'done':
                    stop = threading.Event()
                    watcher = threading.Thread(target=keys.watch_abort, args=(abort, stop), daemon=True)
                    watcher.start()
                    try:
                        result = skills.execute(cell, plan, abort)
                    finally:
                        stop.set()
                        watcher.join()
                    tracker.record(result, step)
                    ui.print(panel.result_panel(result))
                entry['result'] = result
                if bench:
                    injected = bench.injected[n_injected:]
                    n_injected = len(bench.injected)
                    entry['bench'], entry['injected'] = bench_truth(bench), injected
                    ui.print(panel.bench_panel(entry['bench'], injected))
                log.write(entry)

                if action == 'abort' or abort.is_set():
                    end['outcome'] = 'aborted'
                    break
                if action == 'abstain':
                    end['outcome'] = 'abstained'
                    break
                if executed == 'done':
                    if sim:
                        end['outcome'] = 'success' if matches(bench, scenario['expected']) else 'fail'
                    else:
                        verdict = input('Was the instruction carried out? [y/n] ').strip().lower()
                        end['operator_verdict'] = verdict
                        end['outcome'] = 'success' if verdict == 'y' else 'fail'
                    break
            else:
                end['outcome'] = 'max_steps'
    except KeyboardInterrupt:
        abort.set()
        end['outcome'] = 'aborted'
    except SystemExit as e:
        end['outcome'], end['error'] = 'error', str(e)
        raise
    except Exception as e:      # log it, then let it surface
        end['outcome'], end['error'] = 'error', repr(e)
        raise
    finally:
        with contextlib.suppress(Exception):
            control.stopScript()
        with contextlib.suppress(Exception):
            receive.disconnect()
        with contextlib.suppress(Exception):
            s.close()
        if bench:
            end['final_bench'] = bench_truth(bench)
            end['expected'] = scenario['expected']
            end['match'] = matches(bench, scenario['expected'])
            g.set_bench(None)
        log.write(end)
        ui.print(f'outcome: {end["outcome"]}   steps {end["steps"]}   log {os.path.relpath(log.path)}',
                 style='bold')
        if headless:
            print(f'{run_id}: {end["outcome"]} ({end["steps"]} steps)', flush=True)
    end['log'] = log.path
    return end


def main(argv=None):
    parser = make_parser()
    args = parser.parse_args(argv)
    ip, sim = robot.select(parser, args)
    check_args(parser, args, sim)
    run_episode(args, ip, sim)


if __name__ == '__main__':
    main()
