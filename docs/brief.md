# Brief: runbook-cards

**Client (fictional):** Calder Health MSSP, a managed security and IT service provider. Two teams: a SOC with detection rules, and a
help desk with SOPs. Analysts lose time re-reading long, uneven documents under a ticket clock.

**Ask:** one short card per rule or SOP that a person can read in 60 seconds and trust, without trusting the model.

**What we built:** a pipeline in which Claude writes the prose of each card and cites the exact source lines for every field. Code
verifies each quote against those lines, a second model pass checks that each sentence is supported by its lines, queries and ids are
built by code, and anything that fails twice is shown as "needs human" with the reason. The output is one static page per team.

**Why it is safe to read:** no field without a verified span; no model-written query; no link, markup or hidden character in model
text; the page is inert (escaped, script-hash CSP, no external resource); a hard spend limit checked before every request.

**What we measured:** field coverage by verified spans, unsupported claims before and after one redraft, key-field precision and recall
against an answer key, escalation target match (help desk), an injection red-team set, cost per card, and a 20-card human spot
check. Results: see the pilot readout.

**What we would do next with real data:** run on the client's real runbooks in their tenant under their data terms, widen the red-team
set, and keep the "needs human" rate as the headline number, because it is where the pipeline says "I am not sure".

**Out of scope here:** real customer data, response actions, any change to the client's systems.
