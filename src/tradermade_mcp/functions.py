from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_+.-]+")


@dataclass(frozen=True)
class FunctionDoc:
    name: str
    category: str
    description: str
    tags: tuple[str, ...] = ()

    def search_text(self) -> str:
        return " ".join([self.name, self.category, self.description, *self.tags]).lower()

    def full_description(self) -> str:
        return f"{self.description}"


FUNCTION_DOCS: tuple[FunctionDoc, ...] = (
    FunctionDoc(
        name="simple_return",
        category="returns",
        description="Compute simple percentage return from a numeric column. Inputs: column. Output: new column name.",
        tags=("returns", "pct", "change", "performance"),
    ),
    FunctionDoc(
        name="log_return",
        category="returns",
        description="Compute log returns from a numeric column. Inputs: column. Output: new column name.",
        tags=("returns", "log", "change", "performance"),
    ),
    FunctionDoc(
        name="sma",
        category="technical",
        description="Compute a simple moving average over a numeric column. Inputs: column, window. Output: new column name.",
        tags=("moving average", "technical", "trend", "indicator"),
    ),
    FunctionDoc(
        name="ema",
        category="technical",
        description="Compute an exponential moving average over a numeric column. Inputs: column, span. Output: new column name.",
        tags=("moving average", "technical", "trend", "indicator"),
    ),
    FunctionDoc(
        name="spread",
        category="market-microstructure",
        description="Compute ask minus bid. Inputs: bid_column, ask_column. Output: new column name.",
        tags=("bid", "ask", "spread", "quotes"),
    ),
)


_FUNCTION_MAP: dict[str, Callable[[list[dict[str, Any]], dict[str, Any], str], list[dict[str, Any]]]] = {}


def search_functions(query: str, top_k: int = 5) -> list[FunctionDoc]:
    tokens = _tokenize(query)
    scored: list[tuple[float, FunctionDoc]] = []
    lowered = query.strip().lower()
    for doc in FUNCTION_DOCS:
        score = 0.0
        haystack = doc.search_text()
        if lowered == doc.name:
            score += 50.0
        if doc.name in lowered:
            score += 18.0
        if doc.category in lowered:
            score += 8.0
        for token in tokens:
            if token == doc.name:
                score += 12.0
            if token in haystack:
                score += 2.5
            if any(token == tag.lower() for tag in doc.tags):
                score += 5.0
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [doc for _, doc in scored[:top_k]]


def format_search_result(doc: FunctionDoc, rank: int) -> str:
    return f"{rank}. {doc.name} [{doc.category}] (function)\n   {doc.full_description()}"


def apply_pipeline(rows: list[dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = [dict(row) for row in rows]
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"apply step #{index} must be an object")
        function_name = step.get("function")
        if not isinstance(function_name, str) or not function_name:
            raise ValueError(f"apply step #{index} is missing a valid 'function'")
        output = step.get("output")
        if not isinstance(output, str) or not output:
            raise ValueError(f"apply step #{index} is missing a valid 'output'")
        inputs = step.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise ValueError(f"apply step #{index} has invalid 'inputs'")
        handler = _FUNCTION_MAP.get(function_name)
        if handler is None:
            raise ValueError(f"Unknown function: {function_name}")
        current = handler(current, inputs, output)
    return current


def _register(name: str) -> Callable[[Callable[[list[dict[str, Any]], dict[str, Any], str], list[dict[str, Any]]]], Callable[[list[dict[str, Any]], dict[str, Any], str], list[dict[str, Any]]]]:
    def decorator(func: Callable[[list[dict[str, Any]], dict[str, Any], str], list[dict[str, Any]]]) -> Callable[[list[dict[str, Any]], dict[str, Any], str], list[dict[str, Any]]]:
        _FUNCTION_MAP[name] = func
        return func

    return decorator


@_register("simple_return")
def _simple_return(rows: list[dict[str, Any]], inputs: dict[str, Any], output: str) -> list[dict[str, Any]]:
    column = _require_string(inputs, "column")
    previous: float | None = None
    result = []
    for row in rows:
        value = _to_float(row.get(column))
        new_row = dict(row)
        if value is None or previous in (None, 0):
            new_row[output] = None
        else:
            new_row[output] = (value - previous) / previous
        result.append(new_row)
        if value is not None:
            previous = value
    return result


@_register("log_return")
def _log_return(rows: list[dict[str, Any]], inputs: dict[str, Any], output: str) -> list[dict[str, Any]]:
    column = _require_string(inputs, "column")
    previous: float | None = None
    result = []
    for row in rows:
        value = _to_float(row.get(column))
        new_row = dict(row)
        if value is None or previous in (None, 0) or value <= 0:
            new_row[output] = None
        else:
            new_row[output] = math.log(value / previous)
        result.append(new_row)
        if value is not None:
            previous = value
    return result


@_register("sma")
def _sma(rows: list[dict[str, Any]], inputs: dict[str, Any], output: str) -> list[dict[str, Any]]:
    column = _require_string(inputs, "column")
    window = _require_positive_int(inputs, "window")
    result = []
    values: list[float] = []
    for row in rows:
        value = _to_float(row.get(column))
        new_row = dict(row)
        if value is not None:
            values.append(value)
        else:
            values.append(float("nan"))
        recent = [item for item in values[-window:] if not math.isnan(item)]
        new_row[output] = sum(recent) / len(recent) if len(recent) == window else None
        result.append(new_row)
    return result


@_register("ema")
def _ema(rows: list[dict[str, Any]], inputs: dict[str, Any], output: str) -> list[dict[str, Any]]:
    column = _require_string(inputs, "column")
    span = _require_positive_int(inputs, "span")
    alpha = 2.0 / (span + 1.0)
    ema_value: float | None = None
    result = []
    for row in rows:
        value = _to_float(row.get(column))
        new_row = dict(row)
        if value is None:
            new_row[output] = None
        elif ema_value is None:
            ema_value = value
            new_row[output] = ema_value
        else:
            ema_value = alpha * value + (1.0 - alpha) * ema_value
            new_row[output] = ema_value
        result.append(new_row)
    return result


@_register("spread")
def _spread(rows: list[dict[str, Any]], inputs: dict[str, Any], output: str) -> list[dict[str, Any]]:
    bid_column = _require_string(inputs, "bid_column")
    ask_column = _require_string(inputs, "ask_column")
    result = []
    for row in rows:
        bid = _to_float(row.get(bid_column))
        ask = _to_float(row.get(ask_column))
        new_row = dict(row)
        new_row[output] = None if bid is None or ask is None else ask - bid
        result.append(new_row)
    return result


def _require_string(inputs: dict[str, Any], key: str) -> str:
    value = inputs.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Function input '{key}' must be a non-empty string")
    return value


def _require_positive_int(inputs: dict[str, Any], key: str) -> int:
    value = inputs.get(key)
    if isinstance(value, bool):
        raise ValueError(f"Function input '{key}' must be a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdigit():
        parsed = int(value)
    else:
        raise ValueError(f"Function input '{key}' must be a positive integer")
    if parsed <= 0:
        raise ValueError(f"Function input '{key}' must be a positive integer")
    return parsed


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]
