# Braintrust eval gate — example

A minimal, working example of using **Braintrust evals as a required GitHub status check**: a PR can't merge unless the eval clears defined quality thresholds — the same SDLC pattern as "all unit tests pass" or "vulnerability scan clean," but for AI/eval performance.

It's the same idea as branch protection on unit tests, applied to eval scores and performance monitors. Thresholds live in a declarative policy file (`braintrust-gate.yml`) so the quality bar reads like a reviewable governance control, not buried code.

> Companion design doc: *Gating PR Merges on Braintrust Eval Performance* (the "why" and the alternatives). This repo is the runnable "how."

---

## How it works (the three facts that make this work)

1. **A GitHub required status check is just a CI job that must exit `0`.** A GitHub Actions job surfaces as a check; if it exits non-zero, the check fails; branch protection can require it to be green before merge.
2. **`braintrust eval` exits non-zero only when an eval *errors* — not when a score is *low*.** So out of the box, a regression to a terrible-but-non-erroring score still passes. That's the gap this repo closes.
3. **A custom `Reporter` controls the exit code.** `braintrust eval` runs any `Reporter()` it finds and uses its `report_run(...)` return value to decide the exit code. Return `False` → non-zero exit → job fails → required check blocks the merge.

This example registers one config-driven `Reporter` that reads `braintrust-gate.yml` and enforces per-property score floors, score regressions vs a baseline, and metric "monitors" (latency, cost).

```
PR opened ─▶ GitHub Action runs `braintrust eval`
                 │
                 ├─ runs your evals, computes scores + metrics
                 ├─ gate Reporter compares them to braintrust-gate.yml
                 └─ violation? report_run -> False -> exit 1
                          │
                          ▼
              job "eval-gate" fails ─▶ required status check red ─▶ merge blocked
```

## Repo layout

```
braintrust-eval-gate/
├── braintrust-gate.yml             # the policy: thresholds you can edit/review
├── braintrust_gate/
│   ├── __init__.py
│   └── reporter.py                 # config-driven Reporter (reads the policy, gates the run)
├── evals/
│   └── say_hi.eval.py              # example eval; registers the gate at import
├── .github/workflows/eval-gate.yml # CI job that runs the eval + gate
└── requirements.txt
```

The only integration code is the two lines in `evals/say_hi.eval.py`:

```python
from braintrust_gate import register_gate
register_gate()
```

## The policy file

`braintrust-gate.yml` is where the quality bar lives:

```yaml
on_violation: block        # "block" fails the check; "warn" only annotates
baseline: main

scores:
  Levenshtein:
    min: 0.60              # absolute floor on the average score
    max_regression_pp: 5   # max allowed drop vs the baseline experiment (pp)

metrics:
  duration:
    max: 5.0               # absolute ceiling (seconds)
    max_increase: 1.0      # max worsening vs baseline
```

- **`scores`** are your quality monitors — LLM-judge scorers (Factuality, Safety, …) or coded scorers. Each can have an absolute `min` and/or a `max_regression_pp`.
- **`metrics`** are performance monitors — `duration`, `estimated_cost`, token counts, etc. Each can have an absolute `max` and/or a `max_increase` vs baseline.
- **`on_violation: warn`** lets you roll this out in observe-only mode while you calibrate, then flip to `block`.

The scorer/metric **names must match what your eval emits** (e.g. `Levenshtein`, `Factuality`, `duration`).

## Run it locally

```bash
pip install -r requirements.txt
export BRAINTRUST_API_KEY=...          # from https://www.braintrust.dev/app/settings/api-keys
braintrust eval evals
echo "exit code: $?"                    # 0 = passed the gate, 1 = blocked
```

Then **see it block**: lower a threshold below the current score (e.g. set `Levenshtein.min: 0.99`) and re-run — the command exits `1` and prints `::error::` annotations explaining why.

## Wire it up as a required check on GitHub

1. Push this repo to GitHub.
2. Add a repo secret **`BRAINTRUST_API_KEY`** (Settings → Secrets and variables → Actions).
3. Open a PR — the **`eval-gate`** job runs and posts a results comment.
4. Make it blocking: **Settings → Branches → Branch protection rule** (or **Rulesets**) on `main` →
   enable **"Require status checks to pass before merging"** → search for and select **`eval-gate`**.
5. From now on, a PR whose eval drops below the policy can't be merged.

## Two gotchas worth knowing

- **A required check that never runs will hang the PR forever.** If you scope the workflow with `paths:` (only run when `agents/**` changes) but mark the check required globally, PRs that don't touch those paths wait on a check that never reports. Fixes: run on every PR (cheap), add a "passthrough" job that always reports, or use GitHub **Rulesets** with path conditions.
- **The check name must be stable.** Branch protection matches by job name (`eval-gate` here). If you rename the job or change a matrix that alters the check name, the required check silently stops matching.

## Adapting it to your project

- Replace `evals/say_hi.eval.py` with your real `Eval(...)` (Python or TypeScript — the `Reporter` API is identical in JS: `Reporter("name", { reportEval, reportRun })`).
- Add the scorers/metrics you care about to `braintrust-gate.yml`.
- To enforce regression checks deterministically, set `base_experiment_name=` in your `Eval(...)` to your main-branch experiment so `diff` compares against a known baseline.
- Keep `register_gate()` in (or imported by) every eval file you want gated. With exactly one `Reporter` registered, it applies to all evals in the run automatically.

## If your evals are too long/heavy to run inside CI

This example runs the eval **inside the GitHub runner**. For very long agentic evals (or ones needing private data/GPU), use the async pattern instead: create a pending check via GitHub's Checks API, run the eval off-runner, then PATCH the check run to `success`/`failure`. See the companion design doc (Design B) for that variant.
