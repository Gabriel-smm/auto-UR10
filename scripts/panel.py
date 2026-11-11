"""Terminal panels for run_task.py and replay.py (rich).

Every function takes plain dicts, as they are written to the log, so a live
run and a replay draw the same thing.

    header(meta, step)                    TARGET, scenario, seed, decider, step k/max
    state_panel(state, expanded)          the state sent to the decider
    decision_panel(decision, threshold, abstained, executed)
    plan_panel(plan)                      segments, speeds, preflight, before moving
    result_panel(result)                  measured gripper, TCP, ok/reason, duration
    bench_panel(bench, injected)          simulator only: the truth the decider never sees
"""

import json
import re

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BAR = 24                # characters of a full probability bar


def _mm(xyz):
    return '(' + ', '.join(f'{a * 1000:.0f}' for a in xyz[:3]) + ') mm'


def _bar(p, threshold=None):
    n = round(p * BAR)
    text = Text('█' * n, style='green' if threshold is None or p >= threshold else 'yellow')
    text.append('·' * (BAR - n), style='dim')
    return text


def _smallest(report):
    """'Base 99 mm, Shoulder 38.8°' from a preflight report: the smallest plane margin and headroom."""
    planes = [(int(m), n) for n, m in re.findall(r'(\w+) (-?\d+) mm', report)]
    joint = re.search(r'joint headroom (.+?) (-?[\d.]+)°', report)
    parts = [f'{n} {m} mm' for m, n in sorted(planes)[:1]]
    parts += [f'{joint.group(1)} {joint.group(2)}°'] if joint else []
    return ', '.join(parts)


def _gripper(gr):
    if not gr:
        return 'no reading'
    width = f', width {gr["width_mm"]} mm' if gr.get('width_mm') is not None else ''
    return f'gOBJ {gr["obj"]}, pos {gr["pos"]}{width}'

# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


def header(meta, step):
    real = meta['target'] == 'REAL ROBOT'
    target = Text(f' TARGET: {meta["target"]} ({meta["ip"]}) ',
                  style='bold white on red' if real else 'bold black on cyan')
    line = Text.assemble(target, '  ')
    parts = []
    if meta.get('scenario'):
        parts.append(f'scenario {meta["scenario"]}  seed {meta["seed"]}')
    parts.append(f'backend {meta["backend"]}')
    parts.append(f'decider {meta["decider"]}' + (f' ({meta["model"]}, {meta["device"]})'
                                                  if meta['decider'] == 'model' else ''))
    parts.append(f'step {step + 1}/{meta["max_steps"]}')
    parts.append(f'mode {meta["mode"]}')
    line.append('   '.join(parts))
    return line


def state_panel(state, expanded=False):
    if expanded:
        return Panel(Text(json.dumps(state, indent=1)), title='state sent to the decider (s: collapse)',
                     border_style='blue')
    lines = [f'instruction: {state["instruction"]}',
             f'gripper: {_gripper(state["gripper"])} ({state["gripper"]["meaning"]})   '
             f'holding: {state["holding"]}   TCP: {state.get("tcp_level") or ""} {state["tcp_at"]}']
    for name, s in state['slots'].items():
        lines.append(f'  {name:<4} picks {s["picks"]} (gripped {s["gripped"]}, empty {s["empty"]}), '
                     f'placed {s["placed"]}   {s["last"] or ""}')
    if state['history']:
        h = state['history'][-1]
        lines.append(f'last skill: {h["skill"]} {h["args"] or ""} ok={h["ok"]} '
                     f'{h["reason"] or ""} -> {_gripper(h["gripper"])}')
    return Panel(Text('\n'.join(lines)), title=f'state, step {state["step"]} (s: expand)', border_style='blue')


def decision_panel(decision, threshold, abstained, executed=None):
    table = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
    table.add_column('')
    table.add_column('option')
    table.add_column('P(next_skill)')
    table.add_column('', justify='right')
    probs = decision['probs']
    for option, p in sorted(probs.items(), key=lambda kv: -kv[1]):
        mark = '▶' if option == decision['choice'] else ''
        if executed and executed != decision['choice'] and option == executed:
            mark = 'O'
        table.add_row(mark, option, _bar(p, threshold), f'{p:.3f}')

    def fmt(p):
        return '—' if p is None else f'{p:.2f}'
    footer = Text(f'threshold {threshold}   last_ok {fmt(decision["last_ok_prob"])}   '
                  f'task_done {fmt(decision["task_done_prob"])}   latency {decision["latency_s"]:.2f} s')
    if decision.get('vram_peak_mb') is not None:
        footer.append(f'   VRAM peak {decision["vram_peak_mb"]:.0f} MB')
    items = [table, footer]
    if abstained:
        items.append(Text(f'ABSTAINED: P({decision["choice"]}) = {probs.get(decision["choice"], 0):.3f} '
                          f'< {threshold}', style='bold yellow'))
    if (decision.get('extra') or {}).get('error'):
        items.append(Text(f'model error: {decision["extra"]["error"]}', style='bold red'))
    return Panel(Group(*items), title=f'decision: {decision["choice"]}', border_style='magenta')


def plan_panel(plan):
    if plan is None:
        return Panel('no motion', title='plan', border_style='white')
    table = Table(box=box.SIMPLE, pad_edge=False)
    for col in ('#', 'segment', 'motion', 'to', 'preflight'):
        table.add_column(col)
    for i, (seg, check) in enumerate(zip(plan['segments'], plan['preflight'])):
        if check['problems']:
            verdict = Text('; '.join(check['problems']), style='bold red')
        else:
            verdict = Text(f'ok  (min {_smallest(check["report"])})', style='green')
        table.add_row(str(i), seg['kind'], seg['motion'], _mm(seg['to']), verdict)
    speeds = (f'moveL {plan["speed"]} m/s, moveJ {plan["joint_speed"]} rad/s, '
              f'gripper {plan["gripper"] or "—"} (force {plan["force"]})')
    verdict = Text('PREFLIGHT OK', style='bold green') if plan['ok'] else \
        Text(f'REFUSED: {plan["reason"]}', style='bold red')
    title = f'plan: {plan["skill"]} {plan["args"] or ""}'
    return Panel(Group(table, Text(speeds), verdict), title=title, border_style='green' if plan['ok'] else 'red')


def result_panel(result):
    if result is None:
        return Panel('not executed', title='result', border_style='white')
    status = Text('ok', style='bold green') if result['ok'] else Text(f'failed: {result["reason"]}', style='bold red')
    body = Text.assemble(status, f'   gripper {_gripper(result["gripper"])}   TCP {_mm(result["tcp"])}   '
                                 f'{result["duration_s"]:.1f} s')
    return Panel(body, title=f'result: {result["skill"]} {result["args"] or ""}', border_style='cyan')


def bench_panel(bench, injected):
    lines = ['  '.join(f'{n}: {(b or {}).get("id", "—")}' for n, b in bench['slots'].items()),
             f'held: {(bench["held"] or {}).get("id", "—")}   binned: {bench["binned"]}   lost: {bench["lost"]}']
    if injected:
        lines.append('injected this step: ' + ', '.join(f'{e["fault"]} at {e["slot"]}' for e in injected))
    return Panel(Text('\n'.join(lines)), title='BENCH TRUTH (simulator only, never shown to the decider)',
                 border_style='red', style='dim')
