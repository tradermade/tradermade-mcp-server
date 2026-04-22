from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Literal, Optional

from ..formatters import extract_records, parse_response_body


_SPARK_CHARS = " .:-=+*#%@"
_TIME_FORMATS = (
    "%Y-%m-%d-%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


@dataclass(frozen=True)
class WorkflowDoc:
    tool_name: str
    category: str
    description: str
    params: tuple[str, ...]
    tags: tuple[str, ...] = ()

    def search_text(self) -> str:
        return " ".join([self.tool_name, self.category, self.description, *self.params, *self.tags]).lower()

    def full_description(self) -> str:
        return f"{self.description} Inputs: {', '.join(self.params)}."


WORKFLOW_DOCS: tuple[WorkflowDoc, ...] = (
    WorkflowDoc(
        tool_name="analyze_markets",
        category="analytics-component",
        description=(
            "Fetch one or more TraderMade symbols, then return a consolidated comparison with chart lines, "
            "period ranges, returns, and pivot points."
        ),
        params=("symbols", "start_date", "end_date", "interval", "period", "field"),
        tags=("chart", "plot", "compare", "pivot", "range", "table", "multi-market", "stocks", "forex", "cfd"),
    ),
    WorkflowDoc(
        tool_name="validate_market_csv",
        category="analytics-component",
        description=(
            "Compare a user CSV of market OHLC rows against TraderMade daily historical data and report matches, "
            "mismatches, and missing symbols."
        ),
        params=("csv_text", "symbol_column", "date_column", "open_column", "high_column", "low_column", "close_column", "tolerance"),
        tags=("csv", "validate", "compare", "reconcile", "correctness", "ohlc", "data quality"),
    ),
    WorkflowDoc(
        tool_name="analyze_trade_tca",
        category="analytics-component",
        description=(
            "Run basic transaction-cost analysis on a trade CSV using TraderMade tick data when available, "
            "with automatic minute-bar fallback."
        ),
        params=("csv_text", "symbol_column", "execution_time_column", "execution_price_column", "side_column", "quantity_column", "benchmark", "window_minutes"),
        tags=("tca", "transaction cost analysis", "slippage", "execution", "trades", "benchmark"),
    ),
)


def search_workflow_tools(query: str, top_k: int = 5) -> list[WorkflowDoc]:
    tokens = _tokenize(query)
    lowered = query.strip().lower()
    scored: list[tuple[float, WorkflowDoc]] = []
    for doc in WORKFLOW_DOCS:
        score = 0.0
        haystack = doc.search_text()
        if lowered == doc.tool_name.lower():
            score += 50.0
        if doc.tool_name.lower() in lowered:
            score += 18.0
        if doc.category in lowered:
            score += 8.0
        for token in tokens:
            if token == doc.tool_name.lower():
                score += 12.0
            if token in haystack:
                score += 2.5
            if any(token == tag.lower() for tag in doc.tags):
                score += 5.0
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda item: (-item[0], item[1].tool_name))
    return [doc for _, doc in scored[:top_k]]


def format_workflow_search_result(doc: WorkflowDoc, rank: int) -> str:
    return f"{rank}. {doc.tool_name} [{doc.category}] (component)\n   {doc.full_description()}"


def resolve_workflow_tool(name: str) -> WorkflowDoc | None:
    normalized = name.strip().lower()
    for doc in WORKFLOW_DOCS:
        if normalized == doc.tool_name.lower():
            return doc
    return None


def format_workflow_docs(doc: WorkflowDoc) -> str:
    params = "\n".join(f"- {param}" for param in doc.params)
    return (
        f"Component: {doc.tool_name}\n"
        f"Category: {doc.category}\n"
        f"Description: {doc.description}\n"
        f"Inputs:\n{params}"
    )


def register_analytics_tools(
    _mcp,
    readonly_tool: Callable[[], Callable],
    get_http_client: Callable[[], Any],
    get_base_url: Callable[[], str],
    user_agent: str,
):
    @readonly_tool()
    async def analyze_markets(
        symbols: list[str],
        start_date: str,
        end_date: str,
        interval: Literal["daily", "hourly", "minute"] = "daily",
        period: Optional[int] = None,
        field: Literal["open", "high", "low", "close"] = "close",
        normalize_chart: bool = True,
        api_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch one or more symbols and return a consolidated chart, range table, and pivot table."""
        cleaned_symbols = _clean_symbols(symbols)
        if not cleaned_symbols:
            raise ValueError("Provide at least one symbol")
        if len(cleaned_symbols) > 10:
            raise ValueError("At most 10 symbols are supported per request")

        async def fetch_symbol(symbol: str) -> tuple[str, list[dict[str, Any]]]:
            params: dict[str, Any] = {
                "currency": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "format": "records",
            }
            if interval != "daily":
                params["interval"] = interval
            if period is not None:
                params["period"] = period
            records = await _fetch_records(
                path="/timeseries",
                params=params,
                api_key=api_key,
                get_http_client=get_http_client,
                get_base_url=get_base_url,
                user_agent=user_agent,
            )
            normalized = _normalize_ohlc_records(records)
            if not normalized:
                raise RuntimeError(f"No OHLC rows returned for {symbol}")
            return symbol, normalized

        rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
        errors: dict[str, str] = {}
        tasks = [fetch_symbol(symbol) for symbol in cleaned_symbols]
        for symbol, result in zip(cleaned_symbols, await asyncio.gather(*tasks, return_exceptions=True)):
            if isinstance(result, Exception):
                errors[symbol] = str(result)
                continue
            fetched_symbol, rows = result
            rows_by_symbol[fetched_symbol] = rows

        if not rows_by_symbol:
            raise RuntimeError("No market data could be fetched for the requested symbols")

        summary_table = []
        pivot_table = []
        range_table = []
        for symbol, rows in rows_by_symbol.items():
            first_row = rows[0]
            last_row = rows[-1]
            first_value = _require_numeric(first_row, field)
            last_value = _require_numeric(last_row, field)
            period_high = max(_require_numeric(row, field) for row in rows)
            period_low = min(_require_numeric(row, field) for row in rows)
            period_range = period_high - period_low
            latest_bar_range = _require_numeric(last_row, "high") - _require_numeric(last_row, "low")
            change_abs = last_value - first_value
            change_pct = (change_abs / first_value * 100.0) if first_value != 0 else None
            range_pct = (period_range / period_low * 100.0) if period_low != 0 else None

            summary_table.append(
                {
                    "symbol": symbol,
                    "bars": len(rows),
                    "start": first_row["timestamp"],
                    "end": last_row["timestamp"],
                    "start_value": _round(value=first_value),
                    "end_value": _round(value=last_value),
                    "change_abs": _round(value=change_abs),
                    "change_pct": _round(value=change_pct),
                }
            )
            range_table.append(
                {
                    "symbol": symbol,
                    "period_high": _round(value=period_high),
                    "period_low": _round(value=period_low),
                    "period_range": _round(value=period_range),
                    "period_range_pct": _round(value=range_pct),
                    "latest_bar_range": _round(value=latest_bar_range),
                }
            )
            pivot_table.append({"symbol": symbol, "timestamp": last_row["timestamp"], **_pivot_points(last_row)})

        return {
            "source": "/timeseries",
            "field": field,
            "interval": interval,
            "period": period,
            "normalize_chart": normalize_chart,
            "requested_symbols": cleaned_symbols,
            "returned_symbols": list(rows_by_symbol.keys()),
            "errors": errors or None,
            "summary_table": summary_table,
            "range_table": range_table,
            "pivot_table": pivot_table,
            "chart": _build_chart(rows_by_symbol, field=field, normalize=normalize_chart),
        }

    @readonly_tool()
    async def validate_market_csv(
        csv_text: str,
        symbol_column: str = "symbol",
        date_column: str = "date",
        open_column: Optional[str] = "open",
        high_column: Optional[str] = "high",
        low_column: Optional[str] = "low",
        close_column: Optional[str] = "close",
        tolerance: float = 0.0001,
        api_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Compare a CSV of daily OHLC rows against TraderMade historical data."""
        rows = _parse_csv_text(csv_text)
        if not rows:
            raise ValueError("CSV text did not contain any rows")

        compare_columns = {
            "open": open_column,
            "high": high_column,
            "low": low_column,
            "close": close_column,
        }
        active_fields = [field_name for field_name, column in compare_columns.items() if column]
        if not active_fields:
            raise ValueError("At least one OHLC column must be provided")

        grouped: dict[str, set[str]] = {}
        normalized_rows = []
        for line_number, row in enumerate(rows, start=2):
            symbol = _require_cell(row, symbol_column, line_number).upper()
            date_value = _normalize_date_only(_require_cell(row, date_column, line_number))
            normalized_rows.append({"line_number": line_number, "symbol": symbol, "date": date_value, "row": row})
            grouped.setdefault(date_value, set()).add(symbol)

        tm_lookup: dict[tuple[str, str], dict[str, Any]] = {}
        for date_value, symbols_for_date in grouped.items():
            records = await _fetch_records(
                path="/historical",
                params={"currency": ",".join(sorted(symbols_for_date)), "date": date_value},
                api_key=api_key,
                get_http_client=get_http_client,
                get_base_url=get_base_url,
                user_agent=user_agent,
            )
            for record in _normalize_ohlc_records(records):
                record_symbol = _symbol_from_record(record)
                if record_symbol:
                    tm_lookup[(date_value, record_symbol)] = record

        issues = []
        checked_fields = 0
        mismatched_fields = 0
        for item in normalized_rows:
            tm_row = tm_lookup.get((item["date"], item["symbol"]))
            if tm_row is None:
                issues.append(
                    {
                        "line_number": item["line_number"],
                        "symbol": item["symbol"],
                        "date": item["date"],
                        "status": "missing_in_tradermade",
                    }
                )
                continue

            for field_name in active_fields:
                column_name = compare_columns[field_name]
                if column_name is None:
                    continue
                csv_value_raw = item["row"].get(column_name, "")
                csv_value = _to_float(csv_value_raw)
                tm_value = _to_float(tm_row.get(field_name))
                checked_fields += 1
                if csv_value is None or tm_value is None:
                    issues.append(
                        {
                            "line_number": item["line_number"],
                            "symbol": item["symbol"],
                            "date": item["date"],
                            "field": field_name,
                            "csv_value": csv_value_raw,
                            "tradermade_value": tm_row.get(field_name),
                            "status": "missing_value",
                        }
                    )
                    mismatched_fields += 1
                    continue
                difference = csv_value - tm_value
                if abs(difference) > tolerance:
                    mismatched_fields += 1
                    issues.append(
                        {
                            "line_number": item["line_number"],
                            "symbol": item["symbol"],
                            "date": item["date"],
                            "field": field_name,
                            "csv_value": _round(value=csv_value),
                            "tradermade_value": _round(value=tm_value),
                            "difference": _round(value=difference),
                            "status": "mismatch",
                        }
                    )

        return {
            "rows_checked": len(normalized_rows),
            "field_checks": checked_fields,
            "mismatched_field_checks": mismatched_fields,
            "matched_field_checks": checked_fields - mismatched_fields,
            "tolerance": tolerance,
            "issues": issues[:200],
            "truncated_issue_count": max(len(issues) - 200, 0),
        }

    @readonly_tool()
    async def analyze_trade_tca(
        csv_text: str,
        symbol_column: str = "symbol",
        execution_time_column: str = "execution_time",
        execution_price_column: str = "execution_price",
        side_column: str = "side",
        quantity_column: Optional[str] = "quantity",
        benchmark: Literal["nearest_mid", "arrival_mid", "average_mid"] = "nearest_mid",
        window_minutes: int = 5,
        prefer_tick_data: bool = True,
        api_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run basic TCA on a trade CSV using tick data when possible and minute bars otherwise."""
        trade_rows = _parse_csv_text(csv_text)
        if not trade_rows:
            raise ValueError("CSV text did not contain any trades")
        if window_minutes <= 0:
            raise ValueError("window_minutes must be positive")

        results = []
        source_counts: dict[str, int] = {}
        for line_number, row in enumerate(trade_rows, start=2):
            symbol = _require_cell(row, symbol_column, line_number).upper()
            execution_time = _parse_datetime(_require_cell(row, execution_time_column, line_number))
            execution_price = _to_float(_require_cell(row, execution_price_column, line_number))
            if execution_price is None:
                raise ValueError(f"Line {line_number}: execution price is not numeric")
            side = _normalize_side(row.get(side_column, "buy"))
            quantity = _to_float(row.get(quantity_column, "")) if quantity_column else None

            source_used = "minute_timeseries"
            benchmark_price: float | None = None
            tick_error: str | None = None

            if prefer_tick_data:
                try:
                    tick_records = await _fetch_tick_records(
                        symbol=symbol,
                        execution_time=execution_time,
                        window_minutes=window_minutes,
                        api_key=api_key,
                        get_http_client=get_http_client,
                        get_base_url=get_base_url,
                        user_agent=user_agent,
                    )
                    benchmark_price = _benchmark_from_tick_records(tick_records, execution_time, benchmark)
                    source_used = "tick_historical"
                except Exception as exc:
                    tick_error = str(exc)

            if benchmark_price is None:
                minute_records = await _fetch_records(
                    path="/timeseries",
                    params={
                        "currency": symbol,
                        "start_date": _format_dt(execution_time - timedelta(minutes=window_minutes)),
                        "end_date": _format_dt(execution_time + timedelta(minutes=window_minutes)),
                        "interval": "minute",
                        "period": 1,
                        "format": "records",
                    },
                    api_key=api_key,
                    get_http_client=get_http_client,
                    get_base_url=get_base_url,
                    user_agent=user_agent,
                )
                minute_rows = _normalize_ohlc_records(minute_records)
                if not minute_rows:
                    minute_rows = _normalize_ohlc_records(
                        await _fetch_records(
                            path="/minute_historical",
                            params={"currency": symbol, "date_time": _format_dt(execution_time)},
                            api_key=api_key,
                            get_http_client=get_http_client,
                            get_base_url=get_base_url,
                            user_agent=user_agent,
                        )
                    )
                    source_used = "minute_historical"
                benchmark_price = _benchmark_from_bar_records(minute_rows, execution_time, benchmark)

            if benchmark_price is None:
                raise RuntimeError(f"Could not compute benchmark for trade line {line_number}")

            signed_slippage = execution_price - benchmark_price if side == "buy" else benchmark_price - execution_price
            slippage_bps = (signed_slippage / benchmark_price * 10000.0) if benchmark_price != 0 else None
            notional_cost = signed_slippage * quantity if quantity is not None else None
            outcome = "worse" if signed_slippage > 0 else "better" if signed_slippage < 0 else "flat"

            source_counts[source_used] = source_counts.get(source_used, 0) + 1
            results.append(
                {
                    "line_number": line_number,
                    "symbol": symbol,
                    "execution_time": _format_dt(execution_time),
                    "side": side,
                    "execution_price": _round(value=execution_price),
                    "benchmark_price": _round(value=benchmark_price),
                    "benchmark": benchmark,
                    "source": source_used,
                    "signed_slippage": _round(value=signed_slippage),
                    "slippage_bps": _round(value=slippage_bps),
                    "quantity": quantity,
                    "estimated_notional_cost": _round(value=notional_cost),
                    "outcome": outcome,
                    "tick_fallback_reason": tick_error,
                }
            )

        valid_bps = [row["slippage_bps"] for row in results if isinstance(row.get("slippage_bps"), (int, float))]
        return {
            "trades_analyzed": len(results),
            "benchmark": benchmark,
            "window_minutes": window_minutes,
            "prefer_tick_data": prefer_tick_data,
            "source_counts": source_counts,
            "average_slippage_bps": _round(value=sum(valid_bps) / len(valid_bps)) if valid_bps else None,
            "best_slippage_bps": _round(value=min(valid_bps)) if valid_bps else None,
            "worst_slippage_bps": _round(value=max(valid_bps)) if valid_bps else None,
            "trades": results[:200],
            "truncated_trade_count": max(len(results) - 200, 0),
        }

    return (
        analyze_markets,
        validate_market_csv,
        analyze_trade_tca,
    )


async def _fetch_records(
    path: str,
    params: dict[str, Any],
    api_key: Optional[str],
    get_http_client: Callable[[], Any],
    get_base_url: Callable[[], str],
    user_agent: str,
) -> list[dict[str, Any]]:
    effective_key = api_key or os.getenv("TRADERMADE_API_KEY", "")
    if not effective_key:
        raise ValueError("TRADERMADE_API_KEY is not set")

    client = get_http_client()
    query = dict(params)
    query.setdefault("api_key", effective_key)
    response = await client.get(
        f"{get_base_url()}{path}",
        params=query,
        headers={"User-Agent": user_agent},
    )
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")

    kind, payload = parse_response_body(response.text, response.headers.get("content-type"))
    if kind == "json" and isinstance(payload, dict) and ("errors" in payload or "message" in payload):
        raise RuntimeError(json.dumps(payload, sort_keys=True))
    records = extract_records(payload)
    if not records and kind == "csv" and isinstance(payload, list):
        return [dict(row) for row in payload]
    return records


async def _fetch_tick_records(
    symbol: str,
    execution_time: datetime,
    window_minutes: int,
    api_key: Optional[str],
    get_http_client: Callable[[], Any],
    get_base_url: Callable[[], str],
    user_agent: str,
) -> list[dict[str, Any]]:
    start = _format_dt(execution_time - timedelta(minutes=window_minutes))
    end = _format_dt(execution_time + timedelta(minutes=window_minutes))
    for path in (
        f"/tick_historical/{symbol}/{start}/{end}",
        f"/tick_historical_sample/{symbol}/{start}/{end}",
    ):
        try:
            records = await _fetch_records(
                path=path,
                params={"format": "csv"},
                api_key=api_key,
                get_http_client=get_http_client,
                get_base_url=get_base_url,
                user_agent=user_agent,
            )
        except Exception:
            continue
        normalized = []
        for record in records:
            bid = _first_float(record, "bid", "bid_price", "Bid")
            ask = _first_float(record, "ask", "ask_price", "Ask")
            mid = _first_float(record, "mid", "Mid")
            if mid is None and bid is not None and ask is not None:
                mid = (bid + ask) / 2.0
            if mid is None:
                continue
            normalized.append(
                {
                    "timestamp": _parse_any_timestamp(record),
                    "mid": mid,
                }
            )
        if normalized:
            return normalized
    raise RuntimeError("Tick data was unavailable for the requested trade window")


def _normalize_ohlc_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for record in records:
        timestamp = record.get("date_time") or record.get("date") or record.get("timestamp")
        if timestamp is None:
            continue
        row = {
            "timestamp": str(timestamp),
            "symbol": _symbol_from_record(record),
            "open": _to_float(record.get("open")),
            "high": _to_float(record.get("high")),
            "low": _to_float(record.get("low")),
            "close": _to_float(record.get("close")),
        }
        if all(row[key] is not None for key in ("open", "high", "low", "close")):
            normalized.append(row)
    normalized.sort(key=lambda item: item["timestamp"])
    return normalized


def _build_chart(rows_by_symbol: dict[str, list[dict[str, Any]]], field: str, normalize: bool) -> dict[str, Any]:
    series_map: dict[str, list[float]] = {}
    for symbol, rows in rows_by_symbol.items():
        values = [_require_numeric(row, field) for row in rows]
        if normalize and values and values[0] != 0:
            values = [value / values[0] * 100.0 for value in values]
        series_map[symbol] = values

    all_values = [value for values in series_map.values() for value in values]
    if not all_values:
        return {"basis": "normalized" if normalize else "raw", "field": field, "lines": []}

    global_min = min(all_values)
    global_max = max(all_values)
    lines = []
    for symbol, values in series_map.items():
        sampled = _sample_series(values, width=32)
        spark = _sparkline(sampled, lower=global_min, upper=global_max)
        raw_start = _require_numeric(rows_by_symbol[symbol][0], field)
        raw_end = _require_numeric(rows_by_symbol[symbol][-1], field)
        lines.append(
            f"{symbol}: {spark} | start={_round(value=raw_start)} end={_round(value=raw_end)}"
        )
    return {
        "basis": "normalized_to_100" if normalize else "raw",
        "field": field,
        "lines": lines,
    }


def _pivot_points(row: dict[str, Any]) -> dict[str, Any]:
    high = _require_numeric(row, "high")
    low = _require_numeric(row, "low")
    close = _require_numeric(row, "close")
    pivot = (high + low + close) / 3.0
    r1 = 2 * pivot - low
    s1 = 2 * pivot - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    r3 = high + 2 * (pivot - low)
    s3 = low - 2 * (high - pivot)
    return {
        "pivot": _round(value=pivot),
        "r1": _round(value=r1),
        "s1": _round(value=s1),
        "r2": _round(value=r2),
        "s2": _round(value=s2),
        "r3": _round(value=r3),
        "s3": _round(value=s3),
    }


def _benchmark_from_tick_records(
    records: list[dict[str, Any]],
    execution_time: datetime,
    benchmark: Literal["nearest_mid", "arrival_mid", "average_mid"],
) -> float | None:
    mids = [record["mid"] for record in records if record.get("mid") is not None]
    if not mids:
        return None
    if benchmark == "average_mid":
        return sum(mids) / len(mids)
    if benchmark == "arrival_mid":
        return records[0]["mid"]
    dated = [record for record in records if isinstance(record.get("timestamp"), datetime)]
    if not dated:
        return records[0]["mid"]
    nearest = min(dated, key=lambda item: abs(item["timestamp"] - execution_time))
    return nearest["mid"]


def _benchmark_from_bar_records(
    records: list[dict[str, Any]],
    execution_time: datetime,
    benchmark: Literal["nearest_mid", "arrival_mid", "average_mid"],
) -> float | None:
    if not records:
        return None
    prices = [_require_numeric(record, "close") for record in records]
    if benchmark == "average_mid":
        return sum(prices) / len(prices)
    if benchmark == "arrival_mid":
        return prices[0]
    dated = []
    for record in records:
        try:
            timestamp = _parse_datetime(record["timestamp"])
        except Exception:
            continue
        dated.append((timestamp, _require_numeric(record, "close")))
    if not dated:
        return prices[0]
    return min(dated, key=lambda item: abs(item[0] - execution_time))[1]


def _parse_csv_text(csv_text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return []
    return [dict(row) for row in reader]


def _clean_symbols(symbols: list[str]) -> list[str]:
    cleaned = []
    seen: set[str] = set()
    for symbol in symbols:
        normalized = str(symbol).strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _normalize_date_only(value: str) -> str:
    return _parse_datetime(value).strftime("%Y-%m-%d")


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date/time format: {value}")


def _parse_any_timestamp(record: dict[str, Any]) -> datetime | None:
    for key in ("date_time", "timestamp", "date", "time"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            try:
                return _parse_datetime(value)
            except ValueError:
                continue
    return None


def _format_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d-%H:%M")


def _normalize_side(value: Any) -> str:
    text = str(value or "buy").strip().lower()
    if text in {"buy", "b", "long"}:
        return "buy"
    if text in {"sell", "s", "short"}:
        return "sell"
    raise ValueError(f"Unsupported side value: {value}")


def _symbol_from_record(record: dict[str, Any]) -> str | None:
    for key in ("currency", "symbol", "instrument"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    base = record.get("base_currency")
    quote = record.get("quote_currency")
    if isinstance(base, str) and base.strip():
        return f"{base.strip().upper()}{(quote or '').strip().upper()}"
    return None


def _sample_series(values: list[float], width: int) -> list[float]:
    if len(values) <= width:
        return values
    sampled = []
    for index in range(width):
        pos = index * (len(values) - 1) / (width - 1)
        sampled.append(values[int(round(pos))])
    return sampled


def _sparkline(values: list[float], lower: float, upper: float) -> str:
    if not values:
        return ""
    if upper <= lower:
        return _SPARK_CHARS[-1] * len(values)
    chars = []
    scale = len(_SPARK_CHARS) - 1
    for value in values:
        bucket = int(round((value - lower) / (upper - lower) * scale))
        bucket = max(0, min(scale, bucket))
        chars.append(_SPARK_CHARS[bucket])
    return "".join(chars)


def _require_cell(row: dict[str, Any], column: str, line_number: int) -> str:
    value = row.get(column)
    if value is None or str(value).strip() == "":
        raise ValueError(f"Line {line_number}: missing value for column '{column}'")
    return str(value).strip()


def _require_numeric(row: dict[str, Any], key: str) -> float:
    value = _to_float(row.get(key))
    if value is None:
        raise ValueError(f"Missing numeric field: {key}")
    return value


def _first_float(record: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _to_float(record.get(key))
        if value is not None:
            return value
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _round(*, value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in text.replace("/", " ").replace(",", " ").split() if token.strip()]
