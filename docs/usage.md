# Usage

On Windows use `.venv\Scripts\` instead of `.venv/bin/`. Python 3.11 or newer.

## Install and demo (no key, no cost)
```
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/runbook-cards demo
```
`demo` builds `site/security.html` and `site/helpdesk.html` from the committed cards. `runbook-cards check --pack security` re-verifies every span. `runbook-cards eval --replay evals/recorded/<run>` re-runs the scoring from the recorded run, offline.

## Run it live (the only thing that costs money)
```
export ANTHROPIC_API_KEY='<your key>'   # this shell only; nothing is written to disk
.venv/bin/runbook-cards eval --live --budget 3.00 --record evals/recorded/<new-run>
```
PowerShell: `$env:ANTHROPIC_API_KEY = '<your key>'`. `--budget` has no default and is checked before every request against the worst case. Start with a probe of one or two units (`--only <unit id>` or `--limit 2`, which needs `--cards DIR`); it costs a few cents.

## What is sent to the model
The synthetic source text of one unit at a time, plus the card text for the grounding check. Nothing else. The provider's data-retention terms apply to API traffic; read them before pointing this at anything real. Sources and model output are treated as untrusted. Details in [SECURITY.md](../SECURITY.md).
