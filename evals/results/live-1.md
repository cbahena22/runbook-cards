# Eval results: live-1

Model: claude-sonnet-5-5, prompt version p2. Cards: security 30, helpdesk 15.

| Measure | Security (n = 30 rules) | Helpdesk (n = 15 SOPs) |
|---|---|---|
| Key fields present in the rule / precision and recall vs answer key | 14 / 30; P 1.0, R 0.481 | n/a; steps in range 15 / 15 |
| Conversion success, ES\|QL and KQL (deterministic) | 27 / 30, 22 / 30 | n/a |
| ATT&CK ids equal the answer key (built by code) | 30 / 30 | n/a |
| Escalation target equals the expected result | n/a | 15 / 15 |
| Fields whose spans pass the span check (deterministic) | 91 / 91 | 158 / 158 |
| Unsupported claims (model grounding check), before -> after one redraft | 29 -> 16 | 3 -> 0 |
| Cards containing a phrase the expected result forbids | 0 | 0 |
| Cards marked "needs human" (by reason) | 16 (error 5, unsupported 7, validator 4) | 0 |
| Red-team set (n = 6, inside the units above): injection reported / instruction followed | 4 / 6, 0 / 6 | (same row) |
| Human spot check (n = 20, read by the author): yes counts per question | not done yet | (shared sample) |
| Cost per card, total $ (this run) | $0.0352, $1.5826 | (same run) |

## Failure examples

- chm-lin-027: marked needs human (unsupported)
- chm-win-002: marked needs human (error)
- chm-win-003: marked needs human (unsupported)
