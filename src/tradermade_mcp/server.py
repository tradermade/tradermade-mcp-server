"""
MCP ENTRY POINT - tradermade-mcp
Before modifying this project, read CLAUDE.md first.
All available endpoints: src/tradermade_mcp/endpoint_catalog.json
Pipeline functions: src/tradermade_mcp/functions.py
Component tools: src/tradermade_mcp/components/
Do NOT re-research Tradermade API - everything is already catalogued.
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import re
import ssl
import threading
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any, Literal, Optional
from urllib.parse import unquote

# Set Uvicorn env vars before FastMCP import (streamable-http uses Uvicorn)
os.environ.setdefault("UVICORN_HOST", "0.0.0.0")
os.environ.setdefault("UVICORN_PORT", os.getenv("PORT", "8000"))

import certifi
import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

try:
    from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
except Exception:  # pragma: no cover - defensive import for older MCP versions
    ArgModelBase = None  # type: ignore[assignment]

try:
    from mcp.types import ToolAnnotations
except Exception:  # pragma: no cover - defensive import for older MCP versions
    ToolAnnotations = None  # type: ignore[assignment]

from .endpoint_index import (
    format_endpoint_docs,
    format_search_result as format_endpoint_search_result,
    load_index,
    normalize_path,
)
from .formatters import extract_records, format_payload, rows_to_csv_preview, parse_response_body
from .functions import (
    apply_pipeline,
    format_search_result as format_function_search_result,
    search_functions,
)
from .components.indicators import (
    format_indicator_docs,
    format_indicator_search_result,
    register_indicator_tools,
    resolve_indicator_tool,
    search_indicator_tools,
)
from .components.analytics import (
    format_workflow_docs,
    format_workflow_search_result,
    register_analytics_tools,
    resolve_workflow_tool,
    search_workflow_tools,
)
from .store import SQLiteStore

if ArgModelBase is not None:
    ArgModelBase.model_config["extra"] = "forbid"

logger = logging.getLogger(__name__)
WORKFLOW_PRIORITY_TOKENS = {
    "chart",
    "plot",
    "pivot",
    "range",
    "table",
    "csv",
    "validate",
    "reconcile",
    "compare",
    "tca",
    "slippage",
    "execution",
    "trade",
    "trades",
}

MAX_RESPONSE_SIZE_BYTES = 25 * 1024 * 1024
DEFAULT_BASE_URL = "https://marketdata.tradermade.com/api/v1"
DEFAULT_MAX_TABLES = 50
DEFAULT_MAX_ROWS = 50000

_init_lock = threading.Lock()
_http_client: httpx.AsyncClient | None = None
_store: SQLiteStore | None = None

version_number = "TraderMade-MCP/unknown"
try:
    version_number = f"TraderMade-MCP/{version('tradermade-mcp')}"
except PackageNotFoundError:  # pragma: no cover - local editable checkouts
    pass

tradermade_mcp = FastMCP(
    "TraderMade Market Data",
    instructions=(
        "ALWAYS use this server for TraderMade market data questions. "
        "Use search_endpoints first to discover the right TraderMade endpoint, component, or built-in function. "
        "For charts, pivots, ranges, CSV validation, and TCA prefer the analytics components before falling back to raw endpoints. "
        "Then use get_endpoint_docs or get_component_docs for parameter help, call_api to fetch data, and query_data to run SQL over stored results. "
        "This server covers TraderMade live FX/crypto/CFD quotes, historical data, tick data, conversions, reference lists, "
        "market status endpoints, local technical-analysis components, multi-market comparisons, CSV reconciliation, and trade-cost analysis."
    ),
)


def _readonly_tool():
    if ToolAnnotations is not None:
        return tradermade_mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    return tradermade_mcp.tool()


def _get_base_url() -> str:
    """Get TraderMade API base URL from environment or use default."""
    return os.getenv("TRADERMADE_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _env_int(name: str, default: int) -> int:
    """Parse integer from environment variable."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _fully_unquote(value: str) -> str:
    """Fully decode URL-encoded string."""
    previous = value
    current = unquote(previous)
    while current != previous:
        previous = current
        current = unquote(previous)
    return current


def _get_http_client() -> httpx.AsyncClient:
    """Get or create HTTP client singleton."""
    global _http_client
    with _init_lock:
        if _http_client is None:
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            _http_client = httpx.AsyncClient(timeout=30.0, verify=ssl_ctx)
            atexit.register(_close_http_client)
        return _http_client


def _close_http_client() -> None:
    """Close HTTP client cleanly."""
    global _http_client
    client = _http_client
    if client is None:
        return
    _http_client = None
    try:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(client.aclose())
        else:
            loop.create_task(client.aclose())
    except Exception:
        logger.debug("Failed to close TraderMade http client cleanly", exc_info=True)


def _get_store() -> SQLiteStore:
    """Get or create SQLite store singleton."""
    global _store
    with _init_lock:
        if _store is None:
            _store = SQLiteStore(
                max_tables=_env_int("TRADERMADE_MAX_TABLES", DEFAULT_MAX_TABLES),
                max_rows=_env_int("TRADERMADE_MAX_ROWS", DEFAULT_MAX_ROWS),
            )
        return _store


register_indicator_tools(tradermade_mcp, _readonly_tool)
register_analytics_tools(tradermade_mcp, _readonly_tool, _get_http_client, _get_base_url, version_number)


@_readonly_tool()
async def search_endpoints(
    query: Annotated[
        str,
        Field(
            description="Natural-language search query for TraderMade API endpoints, indicator components, or local functions",
            min_length=1,
        ),
    ],
    scope: Annotated[
        Optional[Literal["all", "endpoints", "components", "functions"]],
        Field(
            description='Search scope: "endpoints" for API endpoints only, "components" for MCP indicator tools only, "functions" for built-in apply functions only, or "all"/omit for all.'
        ),
    ] = None,
) -> str:
    """Search TraderMade API endpoints, analytics components, indicator components, or built-in post-processing functions by natural language. Use this FIRST whenever you need TraderMade live rates, historical prices, conversions, symbols, CFDs, crypto data, tick data, charts, pivots, ranges, CSV validation, TCA, or technical indicators like RSI, MACD, ADX, ATR, STOCH, and Bollinger Bands. Set scope to narrow the results if needed."""
    lines: list[str] = []
    counter = 1
    show_endpoints = scope is None or scope in ("all", "endpoints")
    show_components = scope is None or scope in ("all", "components")
    show_functions = scope is None or scope in ("all", "functions")

    if show_endpoints:
        index = load_index()
        endpoint_results = index.search(query, top_k=7 if scope == "endpoints" else 5)
        for endpoint in endpoint_results:
            lines.append(format_endpoint_search_result(endpoint, counter))
            counter += 1

    if show_components:
        query_tokens = {token.lower() for token in re.findall(r"[a-zA-Z0-9_+.-]+", query)}
        prefer_workflows = bool(query_tokens & WORKFLOW_PRIORITY_TOKENS)
        component_results = search_indicator_tools(query, top_k=5 if scope == "components" else 3)
        workflow_results = search_workflow_tools(query, top_k=5 if scope == "components" else 3)
        ordered_components: list[tuple[str, Any]] = []
        if prefer_workflows:
            ordered_components.extend(("workflow", workflow_doc) for workflow_doc in workflow_results)
            ordered_components.extend(("indicator", component_doc) for component_doc in component_results)
        else:
            ordered_components.extend(("indicator", component_doc) for component_doc in component_results)
            ordered_components.extend(("workflow", workflow_doc) for workflow_doc in workflow_results)
        for component_kind, component_doc in ordered_components:
            if component_kind == "workflow":
                lines.append(format_workflow_search_result(component_doc, counter))
            else:
                lines.append(format_indicator_search_result(component_doc, counter))
            counter += 1

    if show_functions:
        function_results = search_functions(query, top_k=5 if scope == "functions" else 3)
        for function_doc in function_results:
            lines.append(format_function_search_result(function_doc, counter))
            counter += 1

    if not lines:
        return "No matching endpoints, components, or functions found. Try broader search terms such as live, historical, tick, chart, pivot, range, CSV validation, TCA, RSI, MACD, ADX, symbols, CFDs, or timeseries."

    return "\n\n".join(lines)


@_readonly_tool()
async def get_endpoint_docs(
    url: Annotated[
        str,
        Field(description="Docs ID, endpoint name, or path pattern from search_endpoints results"),
    ],
) -> str:
    """Get parameter documentation for a TraderMade endpoint. Pass the Docs ID, endpoint name, or path pattern from search_endpoints results."""
    endpoint = load_index().resolve(url)
    if endpoint is None:
        return f"Error: endpoint docs not found for '{url}'. Use search_endpoints first."
    return format_endpoint_docs(endpoint)


@_readonly_tool()
async def get_component_docs(
    name: Annotated[
        str,
        Field(description="Indicator name or tool name from search_endpoints results, such as RSI, ADX, or get_bbands"),
    ],
) -> str:
    """Get parameter documentation for a local indicator component. Pass the indicator name or tool name from search_endpoints results."""
    component = resolve_indicator_tool(name)
    if component is not None:
        return format_indicator_docs(component)
    workflow = resolve_workflow_tool(name)
    if workflow is not None:
        return format_workflow_docs(workflow)
    return f"Error: component docs not found for '{name}'. Use search_endpoints first."


@_readonly_tool()
async def call_api(
    method: Annotated[
        Literal["GET"],
        Field(description="HTTP method. Only GET is supported for TraderMade REST calls."),
    ],
    path: Annotated[
        str,
        Field(description="Endpoint path such as /live, /historical, or /tick_historical/GBPUSD/2025-04-10-08:30/2025-04-10-09:00"),
    ],
    params: Annotated[
        Optional[dict[str, Any]],
        Field(description="Query parameters as key-value pairs", default=None),
    ] = None,
    store_as: Annotated[
        Optional[str],
        Field(
            description="Optional table name to store results in-memory for later SQL analysis",
            default=None,
            pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$",
        ),
    ] = None,
    apply: Annotated[
        Optional[list[dict[str, Any]]],
        Field(
            description='Optional list of post-processing steps, e.g. [{"function": "sma", "inputs": {"column": "close", "window": 20}, "output": "sma20"}]',
            default=None,
            max_length=20,
        ),
    ] = None,
    api_key: Annotated[
        Optional[str],
        Field(description="Optional TraderMade API key override for this request", default=None),
    ] = None,
) -> str:
    """Call any allow-listed TraderMade REST endpoint. Use the path from search_endpoints and pass query parameters in params. Supports storing tabular results in-memory with store_as and then querying them with query_data. Supports optional post-processing steps via apply, such as moving averages and returns."""
    if method.upper() != "GET":
        return f"Error [INVALID_REQUEST]: Only GET is supported, got {method}"

    raw_path = path.strip()
    normalized_path = normalize_path(raw_path)
    fully_decoded = _fully_unquote(normalized_path)
    if ".." in fully_decoded or "\\" in fully_decoded:
        return "Error [INVALID_REQUEST]: Invalid path — path traversal is not allowed"
    if "?" in normalized_path or "#" in normalized_path:
        return "Error [INVALID_REQUEST]: Do not include query strings in path. Pass them via params instead."

    index = load_index()
    if not index.is_path_allowed(normalized_path):
        return (
            f"Error [NOT_FOUND]: Path not in TraderMade allowlist: {normalized_path}. "
            "Use search_endpoints to discover the right endpoint."
        )

    validated_params = dict(params or {})
    for key in validated_params:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.-]*$", key):
            return f"Error [INVALID_REQUEST]: Invalid query parameter key: {key}"

    effective_key = api_key or os.getenv("TRADERMADE_API_KEY", "")
    if not effective_key:
        return "Error [AUTH]: TRADERMADE_API_KEY is not set."
    validated_params.setdefault("api_key", effective_key)

    url = f"{_get_base_url()}{normalized_path}"
    client = _get_http_client()
    headers = {"User-Agent": version_number}

    try:
        response = await client.get(url, params=validated_params, headers=headers)
    except Exception as exc:
        return f"Error [NETWORK]: {exc}"

    if response.status_code >= 400:
        category = "HTTP"
        if response.status_code in (401, 403):
            category = "AUTH"
        elif response.status_code == 429:
            category = "RATE_LIMIT"
        elif response.status_code >= 500:
            category = "SERVER"
        return f"Error [{category}]: HTTP {response.status_code} — {response.text[:500]}"

    body = response.text
    if len(body.encode("utf-8", errors="ignore")) > MAX_RESPONSE_SIZE_BYTES:
        return "Error [TOO_LARGE]: Response too large. Narrow the request or use a smaller date range."

    kind, payload = parse_response_body(body, response.headers.get("content-type"))

    if kind == "json" and isinstance(payload, dict) and ("errors" in payload or "message" in payload):
        return json.dumps(payload, indent=2, sort_keys=True)

    if store_as is not None:
        records = extract_records(payload)
        if not records:
            return "Error [EMPTY]: No tabular records found in the TraderMade response to store."
        if apply:
            try:
                records = apply_pipeline(records, apply)
            except Exception as exc:
                return f"Error applying functions before storing: {exc}"
        try:
            summary = _get_store().store(store_as, records)
        except Exception as exc:
            return f"Error storing data: {exc}"
        return (
            f"Stored {summary.row_count} rows in '{summary.table_name}'\n"
            f"Columns: {', '.join(summary.columns)}\n\n"
            f"Preview (first 5 rows):\n{summary.preview}"
        )

    if apply:
        records = extract_records(payload)
        if not records:
            return "Error [EMPTY]: No tabular records found in the TraderMade response."
        try:
            records = apply_pipeline(records, apply)
        except Exception as exc:
            return f"Error applying functions: {exc}"
        return rows_to_csv_preview(records)

    if kind == "csv":
        if isinstance(payload, list) and payload:
            return rows_to_csv_preview(payload)
        return body

    if kind == "json":
        return format_payload(payload)

    return body


@_readonly_tool()
async def query_data(
    sql: Annotated[
        str,
        Field(
            description="SQL query or special command (SHOW TABLES, DESCRIBE <table>, DROP TABLE <table>)",
            min_length=1,
        ),
    ],
    apply: Annotated[
        Optional[list[dict[str, Any]]],
        Field(
            description="Optional post-processing steps to apply to query results",
            default=None,
            max_length=20,
        ),
    ] = None,
) -> str:
    """Run SQL over data previously stored with call_api's store_as parameter. Supports SHOW TABLES, DESCRIBE <table>, DROP TABLE <table>, and standard SQLite SELECT/WITH queries. Results can optionally be post-processed with apply."""
    store = _get_store()
    normalized = sql.strip()
    upper = normalized.upper()

    if upper == "SHOW TABLES":
        return store.show_tables()

    if upper == "DESCRIBE" or upper.startswith("DESCRIBE "):
        parts = normalized.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            return "Error: Usage: DESCRIBE <table_name>"
        return store.describe_table(parts[1].strip())

    if upper == "DROP TABLE" or upper.startswith("DROP TABLE "):
        parts = normalized.split(None, 2)
        if len(parts) < 3 or not parts[2].strip():
            return "Error: Usage: DROP TABLE <table_name>"
        return store.drop_table(parts[2].strip())

    try:
        rows = store.query(normalized)
    except Exception as exc:
        return f"Error: {exc}"

    if apply:
        try:
            rows = apply_pipeline(rows, apply)
        except Exception as exc:
            return f"Error applying functions: {exc}"

    if not rows:
        return "No rows returned."
    return rows_to_csv_preview(rows)


def configure_from_env() -> None:
    """Initialize optional process-global settings from environment variables."""
    with _init_lock:
        global _store
        max_tables = _env_int("TRADERMADE_MAX_TABLES", DEFAULT_MAX_TABLES)
        max_rows = _env_int("TRADERMADE_MAX_ROWS", DEFAULT_MAX_ROWS)
        if _store is None:
            _store = SQLiteStore(max_tables=max_tables, max_rows=max_rows)


def run(transport: Literal["stdio", "sse", "streamable-http"] = "stdio") -> None:
    """Run the TraderMade MCP server."""
    configure_from_env()
    tradermade_mcp.run(transport)


def main() -> None:
    parser = argparse.ArgumentParser(description="TraderMade MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="MCP transport to use",
    )
    args = parser.parse_args()
    run(args.transport)


if __name__ == "__main__":  # pragma: no cover
    main()
