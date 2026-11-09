# Third-party material

## Python dependencies
Pinned with hashes in `requirements.lock` (runtime) and `requirements-dev.lock` (adds the test and audit tools). Direct
dependencies: PyYAML, Jinja2, jsonschema, pySigma with its Elasticsearch and Kusto backends, and the Anthropic SDK (live runs only).
Licences below are read from the installed package metadata (2026-10-28); `httpx2-jsfetch` is a marker-only package that is not installed on Windows.

| Package | Version | Licence |
|---|---|---|
| anthropic | 2.3.0 | Apache-2.0 |
| pysigma | 1.5.1 | LGPL-2.1-only |
| pysigma-backend-elasticsearch | 2.1.1 | LGPL-3.0-only |
| pysigma-backend-kusto | 1.0.1 | LGPL-3.0-only |
| pyyaml | 6.0.3 | MIT |
| jinja2 | 3.1.6 | BSD-3-Clause |
| markupsafe | 3.0.4 | BSD-3-Clause |
| jsonschema, jsonschema-specifications, referencing, rpds-py, attrs | 4.26.0, 2025.9.1, 0.37.0, 2026.9.1, 26.1.0 | MIT |
| pydantic, pydantic-core, annotated-types, typing-inspection | 2.14.1, 2.50.1, 0.8.0, 0.4.4 | MIT |
| pyparsing | 3.3.3 | MIT |
| httpx2, httpcore2 | 2.16.0 | BSD-3-Clause |
| h11, anyio, sniffio, idna | 0.16.0, 4.15.1, 1.3.1, 3.20 | MIT / BSD-3-Clause / MIT or Apache-2.0 |
| requests | 2.34.2 | Apache-2.0 |
| urllib3, charset-normalizer, jiter, docstring-parser, truststore | 2.8.0, 3.5.2, 0.18.0, 0.18.0, 0.10.5 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| diskcache | 5.6.3 | Apache-2.0 (advisory PYSEC-2026-2447 triaged in `SECURITY.md`) |
| jq, opentelemetry-api, packaging, typing-extensions | 1.13.0, 1.45.1, 26.3, 4.16.0 | BSD-2-Clause, Apache-2.0, Apache-2.0 or BSD-2-Clause, PSF-2.0 |

pySigma and its backends are LGPL. This project imports them as installed libraries and does not modify or copy their code; the
queries it prints are produced by calling them. Pipelines: ES|QL uses the `ecs_windows` pipeline for Windows rules and none for
other rules; KQL uses `microsoft_xdr` (Windows tables only), see `src/runbook_cards/convert.py`.

## MITRE ATT&CK
Technique ids and names in `attack/techniques.json` come from the MITRE ATT&CK enterprise STIX bundle, **version 18.1**
(MITRE's `attack-stix-data` repository), pinned:
- URL: https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack-18.1.json
- sha256: `f857d8f78f2f0c0b7db321a711a39fba98546c1e3076a657684850c83d0962fb` (computed when the file was first downloaded: trust on first use)
- Licence: ATT&CK is (c) The MITRE Corporation, used under the ATT&CK Terms of Use (royalty-free licence, copyright notice kept):
  https://attack.mitre.org/resources/legal-and-branding/terms-of-use/. ATT&CK is a registered trademark of The MITRE Corporation.

`tools/make_techniques.py` holds the version, URL and sha256 as constants and refuses a bundle whose sha256 differs;
the bundle itself is not committed. `attack/techniques.json` records the same version and sha256 and says `"pinned": true`.
Version 18.1 is used because the rules tag T1070.001, T1562.001 and T1562.004, which later releases (19.0 on) mark as revoked.

## Sources
All rules, runbooks and SOPs are synthetic and written for this project. The fictional client is "Calder Health MSSP".
