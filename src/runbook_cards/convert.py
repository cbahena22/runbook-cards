"""Sigma rule -> query for two backends, with pinned pipelines. The model never writes a query.

esql: pySigma Elasticsearch backend (ES|QL) with the `ecs_windows` pipeline for Windows rules;
      other rules use the backend without a pipeline (raw field names).
kql:  pySigma Kusto backend with the `microsoft_xdr` pipeline. It only knows Windows tables,
      so a Linux rule is a recorded failure, not an error.
A failure is a result (`error` set, `query` None); nothing here raises for a rule that cannot convert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BACKENDS = ("esql", "kql")


@dataclass(frozen=True)
class ConvResult:
    query: str | None
    error: str | None
    field_map: dict[str, str | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"query": self.query, "error": self.error, "field_map": dict(self.field_map)}


def _short(exc: BaseException) -> str:
    first = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    first = first.split(". Please use")[0].split(".  ")[0].rstrip(" :.")
    return f"{type(exc).__name__}: {first}"[:240]


def _pipeline(backend: str, rule: dict[str, Any]):
    windows = str(rule.get("logsource", {}).get("product", "")).lower() == "windows"
    if backend == "esql":
        if not windows:
            return None
        from sigma.pipelines.elasticsearch.windows import ecs_windows

        return ecs_windows()
    from sigma.pipelines.microsoftxdr import microsoft_xdr_pipeline

    return microsoft_xdr_pipeline()


def _backend(backend: str, pipeline):
    if backend == "esql":
        from sigma.backends.elasticsearch import ESQLBackend

        return ESQLBackend(pipeline) if pipeline is not None else ESQLBackend()
    from sigma.backends.kusto import KustoBackend

    return KustoBackend(pipeline)


def map_field(rule: dict[str, Any], backend: str, name: str) -> str | None:
    """The backend's name for one rule field, found by running a one-field probe rule through the pipeline."""
    pipeline = _pipeline(backend, rule)
    if pipeline is None:
        return name
    from sigma.rule import SigmaRule

    probe = {
        "title": "probe",
        "logsource": rule["logsource"],
        "detection": {"sel": {name: "x"}, "condition": "sel"},
    }
    try:
        sr = SigmaRule.from_dict(probe)
        pipeline.apply(sr)
        items = sr.detection.detections["sel"].detection_items
        return str(items[0].field) if items and items[0].field else None
    except Exception:  # noqa: BLE001 - a field the pipeline rejects is an honest "no mapping"
        return None


def convert(rule: dict[str, Any], backend: str, key_fields: list[str] | None = None) -> ConvResult:
    """Convert a parsed rule dict. `key_fields` are the fields shown in `field_map`."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend: {backend!r}")
    from sigma.collection import SigmaCollection

    names = key_fields or []
    if backend == "esql" and str(rule.get("logsource", {}).get("product", "")).lower() != "windows":
        return ConvResult(None, "no ECS pipeline for non-Windows rules", {n: None for n in names})
    fmap = {n: map_field(rule, backend, n) for n in names}
    try:
        be = _backend(backend, _pipeline(backend, rule))
        out = be.convert(SigmaCollection.from_dicts([rule]))
        query = out[0] if isinstance(out, list) and out else None
        if not isinstance(query, str) or not query:
            return ConvResult(None, "conversion produced no query", fmap)
        return ConvResult(query, None, fmap)
    except Exception as exc:  # noqa: BLE001 - failures are recorded, never raised
        return ConvResult(None, _short(exc), fmap)
