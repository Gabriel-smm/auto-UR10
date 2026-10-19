"""Choose the target: the real UR10 or the simulator (URSim).

Every script that talks to the robot adds these arguments and calls select()
before connecting. Without --sim the target is the real robot at 192.168.0.1
with the real gripper, so existing usage does not change.

    --sim            simulator at 127.0.0.1, with fake_gripper.py
    --ip ADDRESS     robot IP (default 192.168.0.1); 127.0.0.1 or localhost
                     also selects the simulator
    UR10_SIM=1       environment variable, same as --sim

--sim (or UR10_SIM=1) together with any other --ip is rejected. select()
prints the target before anything connects:

    TARGET: SIMULATOR (127.0.0.1)
    TARGET: REAL ROBOT (192.168.0.1)

In a script:
    import robot
    parser = argparse.ArgumentParser()
    robot.add_args(parser)
    args = parser.parse_args()
    ip, sim = robot.select(parser, args)
    g = robot.gripper(sim)          # fake_gripper or gripper
"""

import importlib
import os

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REAL_IP = '192.168.0.1'
SIM_IP = '127.0.0.1'
SIM_HOSTS = ('127.0.0.1', 'localhost')
ENV_SIM = 'UR10_SIM'                # '1': simulator; '0' or unset: real robot

# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------


def add_args(parser):
    """Add --sim and --ip to an argparse parser."""
    parser.add_argument('--sim', action='store_true',
                        help=f'target the simulator (URSim) at {SIM_IP}; the gripper is '
                             f'fake_gripper.py (also {ENV_SIM}=1)')
    parser.add_argument('--ip', help=f'robot IP (default {REAL_IP})')


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
    ip = SIM_IP if sim else args.ip or REAL_IP
    print(f'TARGET: {"SIMULATOR" if sim else "REAL ROBOT"} ({ip})', flush=True)
    return ip, sim


def gripper(sim):
    """The gripper module for the target: fake_gripper for the simulator, else gripper."""
    return importlib.import_module('fake_gripper' if sim else 'gripper')
