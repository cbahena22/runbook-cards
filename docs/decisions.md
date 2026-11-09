# Decisions

Short records of the choices that shape runbook-cards. Newest design facts first inside each entry: what we chose, why, what it costs.

## 1. One engine, two packs
A pack is a loader plus a unit rule plus a tool schema (`src/runbook_cards/packs/`). Security (Sigma-format rules, one unit per rule) and
IT helpdesk (SOPs, one unit per SOP) share drafting, validation, grounding, the store, the page and the evals.
- Why: the second pack proves the engine is not a one-off, and a bug fixed once is fixed for both.
- Cost: the shared schema is the lowest common shape (text fields, short lists, citations).

## 2. Queries come from pySigma, never from the model
The ES|QL and KQL queries on a security card are produced by the pySigma backends with pinned pipelines. The model writes prose only.
Titles, ATT&CK ids, playbook links and source hashes are also built by code and overwrite anything the model sends.
- Why: a query that looks right and is wrong is the worst failure on a detection card. Conversion either works or is marked as not converted.
- Cost: not every rule converts (the eval table counts the conversions per backend).

## 3. A span for every field
Every model-written field and list item must cite spans `{doc_id, start_line, end_line, quote}`, and the quote must appear in those
lines of one of the unit's documents. The check is deterministic (`validate.py`).
- Why: the reader can see where each sentence came from; an invented sentence has no span to show.
- Cost: short quotes, tighter prose, and a redraft when a quote is not found.

## 4. A model grounding check, one redraft, then "needs human"
The span check proves a quote exists, not that the sentence is supported by it. A second prompt sees each field and only its cited
lines and reports unsupported claims. One redraft is allowed per failure kind; a unit that still fails is written as a "needs human"
card with code-built fields only and a reason, never with unchecked model text.
- Why: a bounded loop with a visible failure state beats an endless retry or a silent pass.
- Cost: about two extra short calls per card.

## 5. One static file per pack, escaped, hashed script, no inline JSON
`site/<pack>.html` is self-contained and safe from `file://`: autoescape on, no `|safe` on card or source text, no inline JSON, no
external resource, no event or style attributes, and a Content-Security-Policy that allows one script and one style by hash.
- Why: card text came from a model and from sources, both untrusted. The page must stay inert whatever they hold.
- Cost: the one script only toggles `hidden` and reads `textContent`; there is no rich client.

## 6. One request-hash store as cache and as replay
`<dir>/requests.jsonl`, `responses.jsonl`, `usage.json`. A request hash covers the model, prompt version, schema version and the full
request body; no header is stored. A hit is reused; a miss under `--replay` is an error, never a live call. A live run retries
recorded failures and keeps every earlier record in its spend total.
- Why: the published results can be re-run for $0 and without a key; a resumed run cannot forget what it spent.
- Cost: a change to the prompt, schema or request shape needs a new recording.

## 7. Committed cards, synthetic sources
The cards, the pages and the recorded run are committed so a reader can open the result without running anything. All rules,
runbooks and SOPs are synthetic and written for this project (fictional client "Calder Health MSSP"). No real rule text, customer name or
employer name appears anywhere.
- Why: nothing in the repository can leak real data, and the published numbers are reproducible.

## 8. A hard spend limit checked before every submit
A live run needs `--budget` (no default). Before each submit the gateway adds the worst case for the group (counted input plus the full
`max_tokens`, times every attempt the SDK may make) to the spend so far; if that exceeds the budget nothing is sent and the rest of the
phase is marked "budget". A call that fails without a usage figure is charged its worst case, never $0.
- Why: the limit holds even when a call times out or is retried.
- Cost: the ledger can overstate the bill. After the first two live runs it showed $2.19 for calls that were probably rejected and
  not billed (see 9); the console is the source of truth for dollars.

## 9. Ask for the tool call with `auto` and no thinking (a forced tool choice failed)
In the first two live runs, `claude-sonnet-5-5` answered a forced `tool_choice` (`tool` or `any`) with HTTP 400 while it was thinking
by default; thinking also spends `max_tokens` before the tool call is written. That is what was observed; the API docs were not re-read for this write-up. The runs got errors, and the old code stored
nothing about the exception, so every card became "needs human" and the cause was invisible.
Now: `tool_choice` is `auto`, the tool is named in the prompt, and thinking is `between_tools`
(`config.toml [request]`). Strict tools (decision 10) cannot carry length or count limits, so the schema sent to the API moves those caps into the
field descriptions, while our own `jsonschema` check still enforces the full caps on every reply. A reply with no tool call, or an
unusable input, is recorded (`stop_reason`, a bounded `partial`, or `detail` with the exception class, HTTP status and the first 300
characters of the provider's message) and the unit ends as "needs human" with no model text.
- Why: failures must be visible in the store, and the request must follow the model's rules.
- Update 2026-10-29: `strict: true` made the API answer HTTP 400 "compiled grammar is too large" for the card schema, so
  `config.toml` now has `strict = false`; the request carries the full schema and our validator is the only shape check. The strict
  path stays in the code and under test (`strict = true`).
- Cost: the tool call is no longer guaranteed by the API; the prompt asks for it and the pipeline treats a missing call as a failure.
- Also: the draft schema is closed and capped (named citation slots, 1-2 short spans each) so one reply cannot run away; its worst
  case is about 1.5k-1.8k tokens against a 3000 limit (`tests/test_schema_bounds.py`).
