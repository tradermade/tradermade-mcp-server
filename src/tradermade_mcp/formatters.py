from __future__ import annotations

import csv
import io
import json
from typing import Any

from .store import flatten_record, rows_to_csv


def parse_response_body(body: str, content_type: str | None = None) -> tuple[str, Any]:
    content_type = (content_type or "").lower()
    if "csv" in content_type:
        return "csv", _parse_csv(body)
    try:
        return "json", json.loads(body)
    except json.JSONDecodeError:
        if _looks_like_csv(body):
            return "csv", _parse_csv(body)
        return "text", body


def extract_records(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []

    if isinstance(payload, list):
        if not payload:
            return []
        if all(isinstance(item, dict) for item in payload):
            return [flatten_record(item) for item in payload]
        return [{"value": item} for item in payload]

    if isinstance(payload, dict):
        if isinstance(payload.get("available_currencies"), dict):
            endpoint = payload.get("endpoint")
            return [
                {
                    "code": code,
                    "name": name,
                    **({"endpoint": endpoint} if endpoint is not None else {}),
                }
                for code, name in payload["available_currencies"].items()
            ]

        if isinstance(payload.get("quotes"), list):
            metadata = {
                key: value
                for key, value in payload.items()
                if key != "quotes" and not isinstance(value, (dict, list))
            }
            rows = []
            for item in payload["quotes"]:
                if isinstance(item, dict):
                    row = flatten_record(item)
                else:
                    row = {"value": item}
                for key, value in metadata.items():
                    row.setdefault(key, value)
                rows.append(row)
            return rows

        if all(not isinstance(value, (dict, list)) for value in payload.values()):
            return [flatten_record(payload)]

        return [flatten_record(payload)]

    return [{"value": payload}]


def format_payload(payload: Any, max_rows: int = 200, preview_rows: int = 50) -> str:
    records = extract_records(payload)
    if records:
        return rows_to_csv_preview(records, max_rows=max_rows, preview_rows=preview_rows)
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, indent=2, sort_keys=True)


def rows_to_csv_preview(
    rows: list[dict[str, Any]],
    max_rows: int = 200,
    preview_rows: int = 50,
) -> str:
    if len(rows) <= max_rows:
        return rows_to_csv(rows)
    preview = rows_to_csv(rows[:preview_rows])
    return (
        f"{preview}\n\n"
        f"NOTE: {len(rows)} rows returned. Showing the first {preview_rows}. "
        "Use store_as + query_data to work with the full dataset."
    )


def maybe_parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _parse_csv(body: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(body))
    return [dict(row) for row in reader]


def _looks_like_csv(body: str) -> bool:
    lines = [line for line in body.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    first, second = lines[0], lines[1]
    return "," in first and "," in second
