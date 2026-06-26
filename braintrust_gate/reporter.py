"""Config-driven Braintrust eval gate.

Registers a Braintrust ``Reporter`` that reads thresholds from a YAML policy
file and decides — for each evaluator — whether the run passes. Returning
``False`` from ``report_run`` makes ``braintrust eval`` exit non-zero, which
fails the GitHub Actions job, which (when marked as a required status check)
blocks the PR merge.

The policy is declarative on purpose: thresholds live in ``braintrust-gate.yml``
so they read like a reviewable governance control, not buried Python.
"""

from __future__ import annotations

import os
from typing import Any

import yaml
from braintrust import Reporter


def _find_policy_path() -> str:
    """Locate the policy file.

    Order: ``BRAINTRUST_GATE_POLICY`` env var, then ``braintrust-gate.yml`` in
    the current directory, then walk up parent directories until we find one.
    """
    override = os.environ.get("BRAINTRUST_GATE_POLICY")
    if override:
        return override

    here = os.getcwd()
    while True:
        candidate = os.path.join(here, "braintrust-gate.yml")
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            # Fall back to the repo root relative to this file.
            return os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "braintrust-gate.yml",
            )
        here = parent


def load_policy(path: str | None = None) -> dict[str, Any]:
    path = path or _find_policy_path()
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _annotate(eval_name: str, level: str, msg: str) -> None:
    # ``::error::`` / ``::warning::`` render as GitHub PR annotations + job log.
    print(f"::{level}::[{eval_name}] {msg}")


def _check_one(evaluator: Any, result: Any, policy: dict[str, Any]) -> bool:
    """Return True if this evaluator clears the policy, else False."""
    eval_name = getattr(evaluator, "eval_name", "eval")
    summary = result.summary
    block = policy.get("on_violation", "block") == "block"
    level = "error" if block else "warning"
    violations = 0

    # ---- scores: absolute floor + max regression vs baseline ----
    score_rules = (policy.get("scores") or {})
    for sname, rule in score_rules.items():
        s = summary.scores.get(sname)
        if s is None:
            _annotate(eval_name, level, f"score '{sname}' not found in results")
            violations += 1
            continue
        if "min" in rule and s.score < rule["min"]:
            _annotate(eval_name, level, f"{sname} {s.score:.3f} < min {rule['min']}")
            violations += 1
        max_reg = rule.get("max_regression_pp")
        if max_reg is not None and s.diff is not None and (-s.diff * 100) > max_reg:
            _annotate(eval_name, level, f"{sname} regressed {(-s.diff)*100:.1f}pp > allowed {max_reg}pp")
            violations += 1

    # ---- metrics ("performance monitors"): absolute ceiling + max increase ----
    metric_rules = (policy.get("metrics") or {})
    for mname, rule in metric_rules.items():
        m = summary.metrics.get(mname)
        if m is None:
            continue  # metric may not be emitted on every run; don't hard-fail
        if "max" in rule and m.metric > rule["max"]:
            _annotate(eval_name, level, f"{mname} {m.metric:.3f}{m.unit} > max {rule['max']}{m.unit}")
            violations += 1
        max_inc = rule.get("max_increase")
        if max_inc is not None and m.diff is not None and m.diff > max_inc:
            _annotate(eval_name, level, f"{mname} rose {m.diff:.3f}{m.unit} > allowed {max_inc}{m.unit}")
            violations += 1

    # Keep the human-readable summary in the job log either way.
    print(summary)

    if violations and block:
        return False
    if violations:
        _annotate(eval_name, "warning", f"{violations} violation(s) — warn mode, not blocking")
    return True


def register_gate(policy_path: str | None = None) -> None:
    """Register the gate reporter. Call this from your eval file(s)."""
    policy = load_policy(policy_path)

    def report_eval(evaluator, result, **kwargs):
        return _check_one(evaluator, result, policy)

    def report_run(results, **kwargs):
        # ``results`` is the list of per-eval booleans from report_eval.
        # Returning False sets a non-zero exit code -> the GitHub job fails.
        ok = all(results)
        if not ok:
            print("::error::Braintrust eval gate FAILED — see annotations above. Merge blocked.")
        else:
            print("Braintrust eval gate passed ✅")
        return ok

    Reporter("braintrust-eval-gate", report_eval=report_eval, report_run=report_run)
