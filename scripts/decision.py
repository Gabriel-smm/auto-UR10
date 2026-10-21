"""What every decider returns, and the plain-language options it chooses from.

A decider is any object with
    decide(state: dict, options: list[str]) -> Decision
where options are strings like 'pick:A', 'place:bin', 'home', 'done'
(from state.Tracker.options). decision_rules.py and decision_model.py
implement it.
"""

from dataclasses import asdict, dataclass, field

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
    if skill == 'pick':
        return (f'Move above slot {arg}, descend, close the gripper on whatever is there, '
                'and lift back above the slot.')
    if skill == 'place' and arg == 'bin':
        return 'Carry the held object above the bin, descend, open the gripper to drop it, and lift back.'
    if skill == 'place':
        return (f'Carry the held object above slot {arg}, descend, open the gripper to leave it '
                'there, and lift back.')
    if skill == 'home':
        return 'Move to the home pose, clear of the bench. Does not change the gripper.'
    if skill == 'done':
        return 'Stop: the instruction has been carried out, or nothing more can be done.'
    raise ValueError(f'unknown option {option!r}')
