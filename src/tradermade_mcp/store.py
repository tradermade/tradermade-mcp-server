from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StoreSummary:
    table_name: str
    row_count: int
    columns: tuple[str, ...]
    preview: str


class SQLiteStore:
    def __init__(self, max_tables: int = 50, max_rows: int = 50000):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._max_tables = max_tables
        self._max_rows = max_rows
        self._meta: dict[str, dict[str, Any]] = {}

    def store(self, name: str, records: list[dict[str, Any]]) -> StoreSummary:
        table_name = sanitize_table_name(name)
        if not records:
            raise ValueError("No records to store")
        if len(records) > self._max_rows:
            raise ValueError(
                f"Refusing to store {len(records)} rows; TRADERMADE_MAX_ROWS is {self._max_rows}"
            )

        if table_name not in self._meta and len(self._meta) >= self._max_tables:
            oldest = min(self._meta.items(), key=lambda item: item[1]["created_at"])[0]
            self.drop_table(oldest)

        flattened = [flatten_record(record) for record in records]
        columns = _ordered_columns(flattened)
        if not columns:
            raise ValueError("Could not determine columns for the records")

        column_types = {column: _infer_sql_type(row.get(column) for row in flattened) for column in columns}
        cur = self._conn.cursor()
        cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        ddl = ", ".join(f'"{column}" {column_types[column]}' for column in columns)
        cur.execute(f'CREATE TABLE "{table_name}" ({ddl})')

        placeholders = ", ".join("?" for _ in columns)
        insert_columns = ", ".join(f'"{column}"' for column in columns)
        cur.executemany(
            f'INSERT INTO "{table_name}" ({insert_columns}) VALUES ({placeholders})',
            [tuple(row.get(column) for column in columns) for row in flattened],
        )
        self._conn.commit()
        self._meta[table_name] = {
            "created_at": time.time(),
            "row_count": len(flattened),
            "columns": tuple(columns),
        }

        preview_rows = self.fetch_rows(f'SELECT * FROM "{table_name}" LIMIT 5')
        preview = rows_to_csv(preview_rows) if preview_rows else "(no preview rows)"
        return StoreSummary(
            table_name=table_name,
            row_count=len(flattened),
            columns=tuple(columns),
            preview=preview,
        )

    def show_tables(self) -> str:
        rows = []
        for name, meta in sorted(self._meta.items()):
            rows.append(
                {
                    "table_name": name,
                    "row_count": meta["row_count"],
                    "created_at_epoch": int(meta["created_at"]),
                }
            )
        if not rows:
            return "No stored tables. Use store_as on call_api first."
        return rows_to_csv(rows)

    def describe_table(self, name: str) -> str:
        table_name = sanitize_table_name(name)
        cur = self._conn.cursor()
        cur.execute(f'PRAGMA table_info("{table_name}")')
        rows = [dict(row) for row in cur.fetchall()]
        if not rows:
            return f"Error: table '{table_name}' does not exist"
        return rows_to_csv(rows)

    def drop_table(self, name: str) -> str:
        table_name = sanitize_table_name(name)
        cur = self._conn.cursor()
        cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        self._conn.commit()
        self._meta.pop(table_name, None)
        return f"Dropped table '{table_name}'"

    def query(self, sql: str) -> list[dict[str, Any]]:
        normalized = sql.strip().lower()
        if not (normalized.startswith("select") or normalized.startswith("with")):
            raise ValueError("Only SELECT and WITH queries are allowed")
        return self.fetch_rows(sql)

    def fetch_rows(self, sql: str) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def sanitize_table_name(name: str) -> str:
    cleaned = "".join(char if (char.isalnum() or char == "_") else "_" for char in name.strip())
    if not cleaned:
        raise ValueError("Table name cannot be empty")
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned[:63]


def flatten_record(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in record.items():
        column = f"{prefix}{key}" if not prefix else f"{prefix}_{key}"
        if isinstance(value, dict):
            result.update(flatten_record(value, prefix=column))
        elif isinstance(value, list):
            result[column] = repr(value)
        else:
            result[column] = value
    return result


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    columns = _ordered_columns(rows)
    lines = [",".join(_escape_csv(column) for column in columns)]
    for row in rows:
        lines.append(",".join(_escape_csv(row.get(column)) for column in columns))
    return "\n".join(lines)


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    columns: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def _escape_csv(value: Any) -> str:
    if value is None:
        text = ""
    elif isinstance(value, float):
        text = repr(value)
    else:
        text = str(value)
    if any(char in text for char in [",", "\n", '"']):
        text = '"' + text.replace('"', '""') + '"'
    return text


def _infer_sql_type(values: Any) -> str:
    has_text = False
    has_real = False
    has_int = False
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            has_int = True
            continue
        if isinstance(value, int):
            has_int = True
            continue
        if isinstance(value, float):
            has_real = True
            continue
        if isinstance(value, str):
            try:
                int(value)
            except ValueError:
                try:
                    float(value)
                except ValueError:
                    has_text = True
                else:
                    has_real = True
            else:
                has_int = True
            continue
        has_text = True
    if has_text:
        return "TEXT"
    if has_real:
        return "REAL"
    if has_int:
        return "INTEGER"
    return "TEXT"
