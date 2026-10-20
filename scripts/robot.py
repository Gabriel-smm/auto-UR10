"""Choose the target: the real UR10 or the simulator (URSim).

Every script that talks to the robot adds these arguments and calls select()
before connecting. Without --sim the target is the real robot at 192.168.0.1
with the real gripper, so existing usage does not change.

    --sim            simulator at 127.0.0.1, with fake_gripper.py
    --ip ADDRESS     robot IP (default 192.168.0.1); 127.0.0.1 or localhost
                     also selects the simulator
    UR10_SIM=1       environment variable, same as --sim
    --scenario PATH  simulator only: a fake_bench.py scenario (JSON) for the
                     fake gripper (also UR10_SIM_SCENARIO); UR10_SIM_SEED
                     overrides its seed. Events go to logs/<name>-<time>.jsonl

--sim (or UR10_SIM=1) together with any other --ip is rejected, and so is a
scenario without the simulator. select()
prints the target before anything connects:

    TARGET: SIMULATOR (127.0.0.1)
    TARGET: REAL ROBOT (192.168.0.1)

In a script:
    import robot
    parser = argparse.ArgumentParser()
    robot.add_args(parser)
    args = parser.parse_args()
    ip, sim = robot.select(parser, args)
    g = robot.gripper(sim, args)    # fake_gripper (with the scenario's bench) or gripper
"""

import importlib
import os
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REAL_IP = '192.168.0.1'
SIM_IP = '127.0.0.1'
SIM_HOSTS = ('127.0.0.1', 'localhost')
ENV_SIM = 'UR10_SIM'                # '1': simulator; '0' or unset: real robot
ENV_SCENARIO = 'UR10_SIM_SCENARIO'  # path to a scenario file, same as --scenario
ENV_SEED = 'UR10_SIM_SEED'          # integer, overrides the scenario seed
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')

# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------


def add_args(parser):
    """Add --sim and --ip to an argparse parser."""
    parser.add_argument('--sim', action='store_true',
                        help=f'target the simulator (URSim) at {SIM_IP}; the gripper is '
                             f'fake_gripper.py (also {ENV_SIM}=1)')
    parser.add_argument('--ip', help=f'robot IP (default {REAL_IP})')
    parser.add_argument('--scenario', help='simulator only: fake_bench scenario file (JSON) '
                                           f'for the fake gripper (also {ENV_SCENARIO})')


def select(parser, args, env=None):
    """Return (ip, sim) and print the target; parser.error on contradictory input."""
    env = os.environ if env is None else env
    flag = env.get(ENV_SIM, '')
    if flag not in ('', '0', '1'):
        parser.error(f'{ENV_SIM}={flag!r}: use 1 for the simulator, 0 or unset for the real robot')

    requested = args.sim or flag == '1'
    if requested and args.ip and args.ip not in SIM_HOSTS:
        source = '--sim' if args.sim else f'{ENV_SIM}=1'
        parser.error(f'{source} targets the simulator at {SIM_IP}, but --ip is {args.ip}')

    sim = requested or args.ip in SIM_HOSTS
    args.scenario = getattr(args, 'scenario', None) or env.get(ENV_SCENARIO) or None
    if args.scenario and not sim:
        parser.error('a scenario needs the simulator: add --sim')

    ip = SIM_IP if sim else args.ip or REAL_IP
    print(f'TARGET: {"SIMULATOR" if sim else "REAL ROBOT"} ({ip})', flush=True)
    return ip, sim


def gripper(sim, args=None, env=None):
    """The gripper module for the target: fake_gripper for the simulator, else gripper.

    With a scenario in args (set by select), the fake gripper gets a
    fake_bench.Bench for it, logging to LOG_DIR.
    """
    g = importlib.import_module('fake_gripper' if sim else 'gripper')
    path = sim and getattr(args, 'scenario', None)
    if path:
        import fake_bench
        env = os.environ if env is None else env
        scenario = fake_bench.load_scenario(path)
        seed = int(env[ENV_SEED]) if env.get(ENV_SEED) else None
        log = os.path.join(LOG_DIR, f'{scenario["name"]}-{time.strftime("%Y%m%d-%H%M%S")}.jsonl')
        bench = fake_bench.Bench(scenario, seed, log)
        g.set_bench(bench)
        print(f'SCENARIO: {bench.name}  seed {bench.seed}  log {os.path.relpath(log)}', flush=True)
    return g
