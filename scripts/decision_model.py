"""Decider backed by a vllm-sr Decision 2.0 model (System One: typed answers, no text).

One system_one call per step, with three questions about the JSON state:

    next_skill  choice  criteria: the valid options, each with a short description
    last_ok     noul    Did the last skill have its intended effect?
    task_done   noul    Has the instruction been carried out?

The answer gives a probability for every option (next_skill) and a yes
probability for each noul question:

    {"answers": {"next_skill": {"choice": "place:C", "confidence": 0.29,
                                "probabilities": {"place:C": 0.59, ...}, "type": "choice"},
                 "last_ok": {"noul": 0.57, "type": "noul"},
                 "task_done": {"noul": 0.74, "type": "noul"}},
     "model": "Decision-2.0-Sol-2B", "usage": {"input_tokens": 1328, "output_tokens": 0}}

Loading: AutoModel.from_pretrained(model, trust_remote_code=True). The model's
own runtime fixes the numerics (BF16 autocast on a GPU, FP32 on the CPU) and
takes no quantization_config. Sol-2B does not fit the 4 GB laptop GPU, even
with bf16_resident; on the CPU it needs about 9 GB of RAM and about 30 s per
decision. Needs requirements-model.txt.

As a module:
    from decision_model import ModelDecider
    decider = ModelDecider('vllm-sr/Decision-2.0-Sol-2B', device='cpu')
    decision = decider.decide(state, options)
"""

import json
import time

from decision import Decision, describe

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = 'vllm-sr/Decision-2.0-Sol-2B'
DEVICES = ('auto', 'cuda', 'cpu')
QUESTION_NEXT = 'Which skill should the robot run next to carry out the instruction?'
QUESTION_LAST_OK = 'Did the last skill have its intended effect?'
QUESTION_DONE = 'Has the instruction been carried out?'
OOM_HINT = ('{model} does not fit in GPU memory. Run it on the CPU with --device cpu '
            '(about 9 GB of RAM for Sol-2B), or add --bf16-resident.')

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
        self.device = str(self.model._runtime_device())
        self.cuda = self.device.startswith('cuda')

    def decide(self, state, options):
        asked = questions(options)
        if self.cuda:
            self.torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        raw = self.model.system_one(state=json.dumps(state), questions=asked)
        latency = time.time() - t0
        vram = round(self.torch.cuda.max_memory_allocated() / 2**20, 1) if self.cuda else None
        return parse(raw, options, asked, latency, vram)
