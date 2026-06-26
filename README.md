# Braintrust eval gate — example

A minimal, working example of using **Braintrust evals as a required GitHub status check**: a PR can't merge unless the eval clears defined quality thresholds — the same SDLC pattern as "all unit tests pass" or "vulnerability scan clean," but for AI/eval performance.

It uses **only what the Braintrust SDK and GitHub Actions already provide** — no custom framework to install. The entire gate is one `Reporter` you define in your own eval file.

---

## How it works (the three facts that make this work)

1. **A GitHub required status check is just a CI job that must exit `0`.** A GitHub Actions job surfaces as a check; if it exits non-zero, the check fails; branch protection can require it to be green before merge.
2. **`braintrust eval` exits non-zero only when an eval *errors* — not when a score is *low*.** So out of the box, a regression to a terrible-but-non-erroring score still passes. That's the gap this example closes.
3. **A custom `Reporter` controls the exit code — natively.** Braintrust's SDK lets you define a `Reporter` with `report_run(...)`; `braintrust eval` runs it and uses its return value as the process exit code. Return `False` → non-zero exit → job fails → required check blocks the merge. This is a documented SDK feature, not extra tooling.

```
PR opened ─▶ GitHub Action runs `braintrust eval`
                 │
                 ├─ runs your evals, computes scores + metrics
                 ├─ your Reporter checks them against your thresholds
                 └─ violation? report_run -> False -> exit 1
                          │
                          ▼
              job "eval-gate" fails ─▶ required status check red ─▶ merge blocked
```

## Repo layout

```
braintrust-eval-gate/
├── evals/
│   └── say_hi.eval.py              # the eval AND the gate Reporter (all in one file)
├── .github/workflows/eval-gate.yml # CI job that runs `braintrust eval`
└── requirements.txt                # braintrust, autoevals — nothing custom
```

## The gate is just a `Reporter`

This is the whole mechanism — copy it into your own eval file and edit the thresholds. It imports nothing but the Braintrust SDK:

```python
from braintrust import Eval, Reporter
from autoevals import Levenshtein

SCORE_FLOORS = {"Levenshtein": 0.60}      # minimum average score (0..1)
MAX_SCORE_REGRESSION = 0.05               # max drop vs baseline (0.05 = 5pp)
METRIC_CEILINGS = {"duration": 5.0}       # absolute ceilings (e.g. seconds)

def report_eval(evaluator, result, **kwargs):
    name = getattr(evaluator, "eval_name", "eval")
    s_sum = result.summary
    ok = True
    for sname, s in s_sum.scores.items():
        floor = SCORE_FLOORS.get(sname)
        if floor is not None and s.score < floor:
            print(f"::error::[{name}] {sname} {s.score:.3f} < floor {floor}"); ok = False
        if s.diff is not None and s.diff < -MAX_SCORE_REGRESSION:
            print(f"::error::[{name}] {sname} regressed {-s.diff*100:.1f}pp vs baseline"); ok = False
    for mname, m in s_sum.metrics.items():
        ceiling = METRIC_CEILINGS.get(mname)
        if ceiling is not None and m.metric > ceiling:
            print(f"::error::[{name}] {mname} {m.metric:.2f}{m.unit} > max {ceiling}{m.unit}"); ok = False
    print(s_sum)
    return ok

def report_run(results, **kwargs):
    return all(results)   # False here => non-zero exit => job fails => merge blocked

Reporter("eval-gate", report_eval=report_eval, report_run=report_run)
```

- **`report_eval`** sees each evaluator's `summary.scores` (averages + `diff` vs baseline) and `summary.metrics` — apply whatever policy you want; it's plain Python.
- **`report_run`** returns the overall pass/fail; its boolean *is* the exit code.
- Define **one** `Reporter` and it applies to every `Eval` in the run automatically. To share it across many eval files, define it in any one file that's part of the run.

See [`evals/say_hi.eval.py`](evals/say_hi.eval.py) for the complete file (Reporter + a deterministic example `Eval`).

## Run it locally

```bash
pip install -r requirements.txt
export BRAINTRUST_API_KEY=...          # from https://www.braintrust.dev/app/settings/api-keys
braintrust eval evals
echo "exit code: $?"                    # 0 = passed the gate, 1 = blocked
```

Then **see it block**: raise a floor above the current score (e.g. `SCORE_FLOORS = {"Levenshtein": 0.99}`) and re-run — the command exits `1` and prints `::error::` annotations explaining why.

## Wire it up as a required check on GitHub

1. Push this repo to GitHub.
2. Add a repo secret **`BRAINTRUST_API_KEY`** (Settings → Secrets and variables → Actions).
3. Open a PR — the **`eval-gate`** job runs and posts a results comment.
4. Make it blocking: **Settings → Branches → Branch protection rule** (or **Rulesets**) on `main` →
   enable **"Require status checks to pass before merging"** → search for and select **`eval-gate`**.
5. From now on, a PR whose eval drops below the policy can't be merged.

The workflow itself is just the official action:

```yaml
- uses: braintrustdata/eval-action@v1
  with:
    api_key: ${{ secrets.BRAINTRUST_API_KEY }}
    runtime: python
    paths: evals
```

The action runs `braintrust eval`, which runs your `Reporter`. Nothing else is needed.

## Two gotchas worth knowing

- **A required check that never runs will hang the PR forever.** If you scope the workflow with `paths:` (only run when `agents/**` changes) but mark the check required globally, PRs that don't touch those paths wait on a check that never reports. Fixes: run on every PR (cheap), add a "passthrough" job that always reports, or use GitHub **Rulesets** with path conditions.
- **The check name must be stable.** Branch protection matches by job name (`eval-gate` here). If you rename the job or change a matrix that alters the check name, the required check silently stops matching.

## Adapting it to your project

- Replace the example `Eval(...)` with your real one (Python or TypeScript — the `Reporter` API is identical in JS: `Reporter("name", { reportEval, reportRun })`).
- Edit `SCORE_FLOORS` / `MAX_SCORE_REGRESSION` / `METRIC_CEILINGS` to your bar. The scorer/metric names must match what your eval emits.
- To enforce regression checks deterministically, set `base_experiment_name=` in your `Eval(...)` to your main-branch experiment so `diff` compares against a known baseline.

## If your evals are too long/heavy to run inside CI

This example runs the eval **inside the GitHub runner**. For very long agentic evals (or ones needing private data/GPU), use the async pattern instead: create a pending check via GitHub's Checks API, run the eval off-runner, then PATCH the check run to `success`/`failure`.

> Note: this gate relies on the **SDK `braintrust eval` CLI** (what `braintrustdata/eval-action@v1` invokes). The `bt` CLI does not execute custom `Reporter`s, so the Reporter-based gate must run through `braintrust eval`.
