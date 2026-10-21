"""Hand-written baseline decider: a state machine over the same state the model sees.

It reads only the state (instruction, gripper reading, per-slot counts,
history) and understands two instructions:

    Put every block on the bench in the bin.
        holding -> place:bin; otherwise pick the first slot not yet emptied
        (a pick that gripped) and not found empty twice; none left -> done
    Move the block in X to Y.
        holding -> place:Y; X gripped and something placed at Y -> done;
        X found empty fewer than twice -> pick:X (one retry); else done

Probabilities are 1.0 for the choice and 0.0 for the rest.

As a module:
    from decision_rules import RulesDecider
    decision = RulesDecider().decide(state, options)
"""

import re
import time

from decision import Decision, split

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EMPTY_TRIES = 2         # a slot is taken as empty after this many picks on nothing
BIN_TASK = re.compile(r'\bevery block\b.*\bin the bin\b', re.I)
MOVE_TASK = re.compile(r'\bmove the block in (\w+) to (\w+)\b', re.I)
OBJ_STOPPED, OBJ_REACHED = 2, 3

# ---------------------------------------------------------------------------
# Decider
# ---------------------------------------------------------------------------


def _last_ok(state):
    """Did the last skill do what it is for, judged from its measured result."""
    if not state['history']:
        return None
    last = state['history'][-1]
    if not last['ok']:
        return 0.0
    obj = last['gripper']['obj']
    if last['skill'] == 'pick':
        return 1.0 if obj == OBJ_STOPPED else 0.0
    if last['skill'] in ('place', 'open_gripper'):
        return 1.0 if obj == OBJ_REACHED else 0.0
    return 1.0


class RulesDecider:
    name = 'rules'

    def choose(self, state, options):
        slots = {n: s for n, s in state['slots'].items() if n != 'bin'}
        move = MOVE_TASK.search(state['instruction'] or '')
        if move:
            src, dst = move.group(1).upper(), move.group(2)
            dst = dst if dst == 'bin' else dst.upper()
            if state['holding']:
                return f'place:{dst}'
            if slots.get(src, {}).get('gripped') and state['slots'].get(dst, {}).get('placed'):
                return 'done'
            if slots.get(src, {}).get('empty', 0) < EMPTY_TRIES and not slots.get(src, {}).get('gripped'):
                return f'pick:{src}'
            return 'done'
        if BIN_TASK.search(state['instruction'] or ''):
            if state['holding']:
                return 'place:bin'
            for name, s in slots.items():
                if not s['gripped'] and s['empty'] < EMPTY_TRIES:
                    return f'pick:{name}'
            return 'done'
        return 'done'                   # an instruction it does not understand

    def decide(self, state, options):
        t0 = time.time()
        choice = self.choose(state, options)
        if choice not in options:       # never return an option the state does not allow
            choice = 'done'
        probs = {o: 1.0 if o == choice else 0.0 for o in options}
        return Decision(choice=choice, probs=probs, last_ok_prob=_last_ok(state),
                        task_done_prob=1.0 if split(choice)[0] == 'done' else 0.0,
                        latency_s=round(time.time() - t0, 6), raw={'rule': choice})
