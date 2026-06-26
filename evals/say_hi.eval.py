"""Example eval gated by a native Braintrust `Reporter`.

Everything here uses only the Braintrust SDK (`from braintrust import ...`).
There is no custom framework to install. `braintrust eval` discovers any
`Reporter()` you define and uses its `report_run(...)` return value as the
process exit code:

    return False  ->  non-zero exit  ->  GitHub job fails  ->  required check blocks merge

The task is deterministic (no LLM call) so the gate's behavior is reproducible
in CI without model access — this example is about the *gate*, not the model.
"""

from braintrust import Eval, Reporter
from autoevals import Levenshtein

# ----------------------------------------------------------------------------
# The quality bar. Edit these to your thresholds. (Names must match what your
# eval emits — scorer names like "Levenshtein"/"Factuality", metrics like
# "duration"/"estimated_cost".)
# ----------------------------------------------------------------------------
SCORE_FLOORS = {
    "Levenshtein": 0.60,          # minimum average score (0..1)
    # "Factuality": 0.90,
    # "Safety": 0.99,
}
MAX_SCORE_REGRESSION = 0.05       # max allowed drop vs baseline (fraction; 0.05 = 5pp)
METRIC_CEILINGS = {
    "duration": 5.0,              # absolute ceiling, seconds
    # "estimated_cost": 0.01,     # $ per case
}


def report_eval(evaluator, result, **kwargs):
    """Return True if this evaluator clears the bar, else False."""
    name = getattr(evaluator, "eval_name", "eval")
    summary = result.summary
    ok = True

    for sname, s in summary.scores.items():
        floor = SCORE_FLOORS.get(sname)
        if floor is not None and s.score < floor:
            print(f"::error::[{name}] {sname} {s.score:.3f} < floor {floor}")
            ok = False
        if s.diff is not None and s.diff < -MAX_SCORE_REGRESSION:
            print(f"::error::[{name}] {sname} regressed {-s.diff*100:.1f}pp vs baseline")
            ok = False

    for mname, m in summary.metrics.items():
        ceiling = METRIC_CEILINGS.get(mname)
        if ceiling is not None and m.metric > ceiling:
            print(f"::error::[{name}] {mname} {m.metric:.2f}{m.unit} > max {ceiling}{m.unit}")
            ok = False

    print(summary)  # keep the human-readable summary in the job log
    return ok


def report_run(results, **kwargs):
    # `results` is the list of per-eval booleans from report_eval.
    # Returning False sets a non-zero exit code -> the GitHub job fails.
    return all(results)


# Registering one Reporter makes it apply to every Eval in the run.
Reporter("eval-gate", report_eval=report_eval, report_run=report_run)


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
    # To enforce regression checks deterministically, pin the baseline to your
    # main-branch experiment, e.g.: base_experiment_name="main",
)
