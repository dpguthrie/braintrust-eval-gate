"""Example eval that is gated by the policy in ``braintrust-gate.yml``.

The task here is deterministic (no LLM call) so the gate's behavior is
reproducible in CI without model access — this example is about the *gate*,
not the model. Swap in your own task/scorers for a real agent.

Discovery: ``braintrust eval`` picks up any file matching ``*.eval.py`` and any
``Reporter()`` registered in a loaded module. We register the gate at import
time below, so it applies to every Eval in the run.
"""

import os
import sys

# Make the repo root importable regardless of where `braintrust eval` is run from,
# so `from braintrust_gate import register_gate` resolves.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from braintrust import Eval  # noqa: E402
from autoevals import Levenshtein  # noqa: E402

from braintrust_gate import register_gate  # noqa: E402

# Register the config-driven gate. This is the whole integration.
register_gate()


def say_hi(name: str) -> str:
    return f"Hi {name}"


Eval(
    "eval-gate-example",  # project name
    data=lambda: [
        {"input": "Alice", "expected": "Hi Alice"},
        {"input": "Bob", "expected": "Hi Bob"},
        {"input": "Carol", "expected": "Hi Carol"},
    ],
    task=say_hi,
    scores=[Levenshtein],
    # Pin the comparison baseline for deterministic regression checks in CI.
    # Point this at your main-branch experiment name once you have one, e.g.:
    # base_experiment_name="main",
)
