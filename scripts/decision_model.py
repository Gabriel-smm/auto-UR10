"""Decider backed by a vllm-sr decision model (System One: typed answers, no text).

One system_one call per step, with three questions. The model does not see the
Tracker state itself but view(state): what is known about each slot, without
the action history, the option words (pick, place) or the status codes. The
model leans towards options whose words the state repeats, so "pick A" in the
history pulled it back to A:

    {"instruction": "Move the block in A to C.", "gripper": "open, empty",
     "blocks_removed_from": ["A"], "blocks_put_in": ["C"], "blocks_in_bin": 0,
     "found_empty": [], "not_visited_yet": ["B"]}

    next_skill  choice  criteria: the valid options, each with a short description
    last_ok     noul    Did the most recent action do what it was meant to?
    task_done   noul    Do the blocks' current positions already satisfy the instruction?

The answer gives a probability for every option (next_skill) and a yes
probability for each noul question:

    {"answers": {"next_skill": {"choice": "place:A", "confidence": 0.49,
                                "probabilities": {"place:A": 0.52, "place:C": 0.43, ...}, "type": "choice"},
                 "last_ok": {"noul": 0.11, "type": "noul"},
                 "task_done": {"noul": 0.20, "type": "noul"}},
     "model": "d3-lite", "usage": {"input_tokens": 1341, "output_tokens": 0}}

Loading: AutoModel.from_pretrained(model, trust_remote_code=True); each
model's own runtime fixes its numerics and takes no quantization_config.

    vllm-sr/d3-lite (default)       0.85 B; on the 4 GB laptop GPU: 1.6 GB loaded,
                                    1.8 GB peak, about 0.5 s per decision
    vllm-sr/Decision-2.0-Sol-2B     1.88 B; does not fit the 4 GB GPU, even with
                                    --bf16-resident; on the CPU about 9 GB of RAM
                                    and 30-55 s per decision

Needs requirements-model.txt.

As a module:
    from decision_model import ModelDecider
    decider = ModelDecider()                    # d3-lite, GPU if there is one
    decision = decider.decide(state, options)
"""

import json
import time

from decision import Decision, describe
from state import BINS, OBJ_STOPPED

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = 'vllm-sr/d3-lite'
DEVICES = ('auto', 'cuda', 'cpu')
QUESTION_NEXT = 'Given where the blocks are now and what the instruction asks, which action comes next?'
QUESTION_LAST_OK = ('Did the most recent action do what it was meant to (for example, the gripper '
                    'closed on a block when taking one)?')
QUESTION_DONE = "Do the blocks' current positions already satisfy the instruction?"
OPEN_BELOW = 128        # gripper pos under which an empty gripper reads as open
OOM_HINT = ('{model} does not fit in GPU memory: use a smaller model (the default, '
            f'{MODEL}, fits a 4 GB GPU) or run it on the CPU with --device cpu.')

# ---------------------------------------------------------------------------
# What the model sees
# ---------------------------------------------------------------------------


def _gripper(gr):
    if gr['obj'] == OBJ_STOPPED:
        return f'holding a block, {gr["width_mm"]} mm wide'
    if gr['obj'] == 3:
        return 'open, empty' if gr['pos'] < OPEN_BELOW else 'closed, empty'
    return gr['meaning']


def _slots(state, event):
    return [n for n, s in state['slots'].items() if s.get('event') == event and n not in BINS]


def view(state):
    """What the model sees: the instruction, the gripper, and what is known about each slot.

    No action history: the model leans towards options whose slot the state
    names often, so a history of attempts at A pulls it back to A.
    """
    return {'instruction': state['instruction'],
            'gripper': _gripper(state['gripper']),
            'blocks_removed_from': _slots(state, 'taken'),
            'blocks_put_in': _slots(state, 'released'),
            'blocks_in_bin': sum(s['placed'] for n, s in state['slots'].items() if n in BINS),
            'found_empty': _slots(state, 'empty'),
            'not_visited_yet': [n for n, s in state['slots'].items()
                                if s.get('event') in (None, 'failed') and n not in BINS]}

# ---------------------------------------------------------------------------
# Questions and answers
# ---------------------------------------------------------------------------


def questions(options):
    """The three questions for one step; next_skill criteria come from the options only."""
    return {
        'next_skill': {'type': 'choice', 'instructions': QUESTION_NEXT,
                       'criteria': {o: describe(o) for o in options}},
        'last_ok': {'type': 'noul', 'instructions': QUESTION_LAST_OK},
        'task_done': {'type': 'noul', 'instructions': QUESTION_DONE},
    }


def _noul(answers, key):
    value = (answers.get(key) or {}).get('noul')
    return float(value) if isinstance(value, (int, float)) else None


def parse(raw, options, asked=None, latency_s=0.0, vram_peak_mb=None):
    """Decision from a system_one answer.

    choice is the option with the highest probability. An answer without
    probabilities (for example max_length_exceeded) gives all zeros and
    'done', so the step falls below any threshold and abstains.
    """
    answers = raw.get('answers', {}) if isinstance(raw, dict) else {}
    nxt = answers.get('next_skill') or {}
    given = nxt.get('probabilities') or {}
    probs = {o: float(given.get(o, 0.0)) for o in options}
    error = None if given else (nxt.get('error') or answers.get('error') or 'no probabilities in the answer')
    choice = max(probs, key=probs.get) if given else 'done'
    return Decision(choice=choice, probs=probs,
                    last_ok_prob=_noul(answers, 'last_ok'), task_done_prob=_noul(answers, 'task_done'),
                    latency_s=round(latency_s, 3), raw=raw, questions=asked, vram_peak_mb=vram_peak_mb,
                    extra={'confidence': nxt.get('confidence'), 'model_choice': nxt.get('choice'),
                           'usage': raw.get('usage') if isinstance(raw, dict) else None,
                           'error': error})

# ---------------------------------------------------------------------------
# Decider
# ---------------------------------------------------------------------------


def _device_of(model):
    """Where the model runs: the runtime's own answer if it has one, else its parameters."""
    if hasattr(model, '_runtime_device'):        # Decision 2.0
        return str(model._runtime_device())
    param = next(model.parameters(), None)       # d3
    return str(param.device) if param is not None else 'cpu'


class ModelDecider:
    name = 'model'

    def __init__(self, model=MODEL, device='auto', bf16_resident=False):
        import torch
        from transformers import AutoModel

        self.torch, self.model_name = torch, model
        kw = {'trust_remote_code': True, 'device_map': device}
        if bf16_resident:
            kw['bf16_resident'] = True
        try:
            self.model = AutoModel.from_pretrained(model, **kw)
        except torch.OutOfMemoryError:
            raise SystemExit(OOM_HINT.format(model=model))
        self.device = _device_of(self.model)
        self.cuda = self.device.startswith('cuda')

    def decide(self, state, options):
        asked, seen = questions(options), view(state)
        if self.cuda:
            self.torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        raw = self.model.system_one(state=json.dumps(seen), questions=asked)
        latency = time.time() - t0
        vram = round(self.torch.cuda.max_memory_allocated() / 2**20, 1) if self.cuda else None
        decision = parse(raw, options, asked, latency, vram)
        decision.extra['model_state'] = seen
        return decision
