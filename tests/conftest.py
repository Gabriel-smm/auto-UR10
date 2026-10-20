"""Shared fixtures. The tests need no robot, no URSim and no gripper."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import fake_bench  # noqa: E402

A = [0.26, 0.35, -0.07, 0.0, 0.0, 0.0]
B = [0.0, 0.44, -0.07, 0.0, 0.0, 0.0]
C = [-0.27, 0.35, -0.07, 0.0, 0.0, 0.0]
BIN = [0.0, 0.64, 0.0, 0.0, 0.0, 0.0]
AWAY = [0.0, 0.5, 0.3]


def scenario(seed=1, slip_signal='silent', **faults):
    """A on the bench with a 40 mm block, B with a 20 mm block, C empty, and a bin."""
    return fake_bench.parse_scenario({
        'name': 'test', 'seed': seed,
        'slots': {'A': {'pose': A, 'block': {'id': 'a', 'width_mm': 40}},
                  'B': {'pose': B, 'block': {'id': 'b', 'width_mm': 20}},
                  'C': {'pose': C},
                  'bin': {'pose': BIN, 'bin': True}},
        'faults': faults, 'slip_signal': slip_signal})


@pytest.fixture
def make_bench():
    return lambda seed=1, **kw: fake_bench.Bench(scenario(seed, **kw))
