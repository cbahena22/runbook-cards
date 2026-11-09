"""Worst-case size of a tool input: the longest JSON a schema allows, in characters and in estimated tokens.

Only the keywords the draft schemas use are read (type, properties, items, maxItems, maxLength, maximum). A schema with an
unbounded string, array or integer has no worst case and raises, so a missing cap cannot slip in unnoticed.
"""
from __future__ import annotations

from typing import Any

CHARS_PER_TOKEN = 3.0  # deliberately low: JSON punctuation and identifiers tokenise worse than prose


def max_chars(schema: dict[str, Any]) -> int:
    """Characters of the longest compact JSON document the schema accepts (every property present, every cap reached)."""
    kind = schema.get("type")
    if kind == "string":
        if "maxLength" not in schema:
            raise ValueError("a string without maxLength has no worst case")
        return 2 + int(schema["maxLength"])
    if kind == "integer":
        if "maximum" not in schema:
            raise ValueError("an integer without maximum has no worst case")
        return len(str(int(schema["maximum"])))
    if kind == "array":
        if "maxItems" not in schema:
            raise ValueError("an array without maxItems has no worst case")
        n = int(schema["maxItems"])
        return 2 + n * max_chars(schema["items"]) + max(n - 1, 0)
    if kind == "object":
        props = schema.get("properties")
        if not props or schema.get("additionalProperties") is not False:
            raise ValueError("an object needs listed properties and additionalProperties false to have a worst case")
        return 2 + sum(len(k) + 3 + max_chars(v) for k, v in props.items()) + len(props) - 1
    raise ValueError(f"unsupported schema type {kind!r}")


def max_tokens_estimate(schema: dict[str, Any]) -> int:
    return int(max_chars(schema) / CHARS_PER_TOKEN) + 1
