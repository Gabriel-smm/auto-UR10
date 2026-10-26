"""What every decider returns, and the plain-language options it chooses from.

A decider is any object with
    decide(state: dict, options: list[str]) -> Decision
where options are strings like 'move:A', 'down', 'close', 'done'
(from state.Tracker.options). decision_rules.py and decision_model.py
implement it.

next_primitives(goal, state) turns a goal ('pick:X', 'place:Y', 'done') into
the primitive(s) that make progress from where the arm and gripper are; the
rules decider and summarize.py's judge both use it.
"""

from dataclasses import asdict, dataclass, field

from state import BINS, closed_empty

# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


@dataclass
class Decision:
    choice: str                         # one of the options
    probs: dict                         # option -> probability of next_skill
    last_ok_prob: float | None          # P(the last skill had its intended effect)
    task_done_prob: float | None        # P(the instruction is complete)
    latency_s: float
    raw: object = None                  # the decider's raw answer, for the log
    questions: dict | None = None       # what was asked (model only)
    vram_peak_mb: float | None = None   # model only
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def split(option):
    """'pick:A' -> ('pick', 'A'); 'home' -> ('home', None)."""
    skill, _, arg = option.partition(':')
    return skill, arg or None


def describe(option):
    """Short description of an option, as shown to the model."""
    skill, arg = split(option)
    if skill == 'move' and arg == 'bin':
        return 'Move the gripper to above the bin. It does not go down or change the gripper.'
    if skill == 'move':
        return (f'Move the gripper to 10 cm above {arg}. It does not go down into {arg} '
                'or change the gripper.')
    if skill == 'down':
        return 'Lower the gripper from above the slot it is over down to block height.'
    if skill == 'up':
        return 'Raise the gripper from the slot it is in back up to 10 cm above it.'
    if skill == 'close':
        return 'Close the gripper, gripping a block if one is between the fingers.'
    if skill == 'open':
        return 'Open the gripper, letting go of anything it holds.'
    if skill == 'pick':
        return (f'Take the block that is in {arg} into the empty gripper. '
                f'Only useful while a block is still believed to be in {arg}.')
    if skill == 'place' and arg == 'bin':
        return 'Drop the block now held into the bin.'
    if skill == 'place':
        return f'Set the block now held down in {arg} and let go of it.'
    if skill == 'home':
        return 'Move clear of the bench to the home pose, without changing the gripper.'
    if skill == 'done':
        return ('Stop: the instruction is fully carried out, or every slot has been checked '
                'and nothing is left to do.')
    raise ValueError(f'unknown option {option!r}')

# ---------------------------------------------------------------------------
# Goals to primitives
# ---------------------------------------------------------------------------


def next_primitives(goal, state):
    """Primitives that make progress towards goal from the current state; the first is
    the one the rules decider takes.

        pick:X   open a closed empty gripper; up if down elsewhere; move:X; down; close
        place:Y  up if down elsewhere; move:Y; down; open (over the bin, open from above too)
        done     done
    """
    skill, slot = split(goal)
    if skill == 'done':
        return ['done']
    at, level = state['tcp_at'], state['tcp_level']
    if skill == 'pick':
        if closed_empty(state['gripper']):
            return ['open']
        if at != slot:
            return ['up'] if level == 'down' else [f'move:{slot}']
        return ['down'] if level == 'above' else ['close']
    if skill == 'place':
        if at != slot:
            return ['up'] if level == 'down' else [f'move:{slot}']
        if level == 'above':
            return ['open', 'down'] if slot in BINS else ['down']
        return ['open']
    raise ValueError(f'unknown goal {goal!r}')
