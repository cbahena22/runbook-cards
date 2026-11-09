# Security policy

runbook-cards is a small demo project. It runs on synthetic data only and holds no customer or personal data.

## Reporting a vulnerability
Use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability").
Please do not open a public issue for a security problem.

## What is in scope
- The sources (rules, runbooks, SOPs) are **untrusted text**. The loader caps file count, size and line length, stays under
  the pack root, refuses symlinks, bidirectional controls and YAML anchors or aliases, and makes zero-width characters visible.
- Model output is **untrusted**. Every drafted field must pass the validator before it reaches a card: a quoted span for each
  field that is found verbatim in the cited lines, no links, no markup, no fence brackets, no invisible characters, key fields
  that exist in the rule. Queries, ATT&CK ids, titles and links are built by code, never taken from the model. A card that
  fails twice is marked "needs human" and carries no model text.
- The generated page is one static file: every value is escaped, there is no inline JSON, no external resource and no event
  attribute, and the Content-Security-Policy allows exactly one script and one style by hash.
- Prompt injection inside a source is reported by the model and, separately, checked by a red-team set in the evals.

## Keys and spend
- The only secret is `ANTHROPIC_API_KEY`, read from the environment for a live run. It is never written to a file, a store or a
  log; the request store holds the request body, the reply and token counts, no header. A failed call also keeps the exception
  class, the HTTP status, up to 300 characters of the provider's error message and, for an unfinished or tool-less reply, the
  first and last 400 characters of the unvalidated model output (`detail`, `partial`); committed recordings can contain them.
  Never a header or the key.
- A live run needs `--budget` (no default). The spend limit is checked before every submit against the worst case: the counted
  input plus the full `max_tokens`, times every retry the SDK may make. Replay, demo, build and check never load the SDK and need
  no key.

## Supply chain
- Runtime and dev dependencies are pinned with hashes in `requirements.lock` and `requirements-dev.lock`; install with
  `--require-hashes`. `THIRD_PARTY.md` lists each dependency and the pinned ATT&CK data (version and sha256).

## Dependency advisories (triaged)
- `diskcache` 5.6.3 (PYSEC-2026-2447; `pip-audit --desc`: "uses Python pickle for serialization by default. An attacker with
  write access to the cache directory can achieve arbitrary code execution when a victim application reads from the cache").
  No fixed release exists. It is pulled in by pySigma 1.5.1, which uses it only in `sigma.data.mitre_attack` and
  `sigma.data.mitre_d3fend` to cache downloaded MITRE data under `~/.cache/pysigma`. Those modules load lazily, and only
  pySigma's tag validator (`sigma.validators.core.tags`) reads them. This project never runs pySigma validators, never sets
  a cache directory and never downloads MITRE data (the ATT&CK ids come from the pinned `attack/techniques.json`). After
  the full test suite and a rule conversion, `~/.cache/pysigma` does not exist, so nothing is ever read from a cache.
  The package cannot be dropped without dropping pySigma. Re-check when updating the locks.
