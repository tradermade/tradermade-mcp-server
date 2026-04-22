# CLAUDE.md

Read this file before modifying the project.

Rule: Never research Tradermade API docs again - all endpoints are in endpoint_catalog.json.

## Project Structure

Runtime and support files only. Analysis docs are intentionally excluded here.

```text
app.py
Procfile
pyproject.toml
run_tradermade_mcp.cmd
run_tradermade_mcp.py
tradermade-full.txt
test_mcp.py
test_parser_inline.py
test_storage.py
src/tradermade_mcp/__init__.py
src/tradermade_mcp/endpoint_catalog.json
src/tradermade_mcp/endpoint_index.py
src/tradermade_mcp/formatters.py
src/tradermade_mcp/functions.py
src/tradermade_mcp/parser.py
src/tradermade_mcp/server.py
src/tradermade_mcp/store.py
```

## src/tradermade_mcp Files

- `__init__.py`: Package metadata only. It exports `__version__`.
- `run_tradermade_mcp.py`: Stdlib-only bootstrap launcher. It creates `venv`, installs the package when needed, optionally loads `.env`, and then execs into `tradermade_mcp.server`.
- `run_tradermade_mcp.cmd`: Windows wrapper that finds a Python interpreter and forwards to `run_tradermade_mcp.py`.
- `server.py`: Main FastMCP server. Defines the four MCP tools, reads env vars, manages the HTTP client, and manages the in-memory SQLite store.
- `endpoint_catalog.json`: Static allowlist of TraderMade endpoints, parameter docs, examples, and notes. This is the runtime source of truth for supported endpoints.
- `endpoint_index.py`: Loads `endpoint_catalog.json`, builds the search index, resolves endpoint IDs and paths, formats docs, and validates allowed paths.
- `formatters.py`: Parses JSON/CSV/text API responses, extracts tabular records, and formats previews for MCP output.
- `functions.py`: Defines built-in post-processing functions and the search metadata for them. This powers `apply` in `call_api` and `query_data`.
- `parser.py`: Parses `tradermade-full.txt` into endpoint objects. It exists as a utility/test helper, not as part of the runtime server path.
- `store.py`: In-memory SQLite storage layer for `store_as`, `SHOW TABLES`, `DESCRIBE`, `DROP TABLE`, and `SELECT/WITH` queries.

## How The MCP Server Starts

- Python console entry point in `pyproject.toml`: `tradermade_mcp = "tradermade_mcp.server:main"`
- Recommended command: `tradermade_mcp`
- Equivalent module command: `python -m tradermade_mcp.server`
- Bootstrap command: `python run_tradermade_mcp.py --api-key YOUR_TRADERMADE_API_KEY`
- Transport options: `stdio`, `sse`, `streamable-http`
- Default transport: `stdio`, unless `MCP_TRANSPORT` is set
- Web deployment path:
  `Procfile` runs `uvicorn app:app --host 0.0.0.0 --port $PORT`
  `app.py` starts the MCP server in `sse` mode and reverse-proxies requests to localhost

## Environment Variables

Note: the code does not load `.env` files automatically. Values must be exported in the shell or passed in Claude Desktop / Claude Code config.

- `TRADERMADE_API_KEY`: Required for real TraderMade API calls.
- `TRADERMADE_API_BASE_URL`: Optional base URL. Defaults to `https://marketdata.tradermade.com/api/v1`.
- `MCP_TRANSPORT`: Optional transport override for `main()`. Valid values: `stdio`, `sse`, `streamable-http`.
- `TRADERMADE_MAX_TABLES`: Optional cap for stored in-memory tables. Default is `50`.
- `TRADERMADE_MAX_ROWS`: Optional cap for stored rows per table. Default is `50000`.
- `PORT`: Used by `app.py` / `Procfile` web deployment to choose the listening port.

## Implemented Endpoints

- `live_currencies_list` -> `/live_currencies_list`
- `live_crypto_list` -> `/live_crypto_list`
- `historical_currencies_list` -> `/historical_currencies_list`
- `cfd_list` -> `/cfd_list`
- `streaming_currencies_list` -> `/streaming_currencies_list`
- `live` -> `/live`
- `historical` -> `/historical`
- `tick_historical` -> `/tick_historical/{symbol}/{start_date}/{end_date}`
- `tick_historical_sample` -> `/tick_historical_sample/{symbol}/{start_date}/{end_date}`
- `minute_historical` -> `/minute_historical`
- `hour_historical` -> `/hour_historical`
- `timeseries` -> `/timeseries`
- `pandasDF` -> `/pandasDF`
- `convert` -> `/convert`
- `market_open_status` -> `/market_open_status`
- `market_opening_times` -> `/market_opening_times`

## Tools Exposed To Claude

Actual MCP tools exposed by `server.py`:

- `search_endpoints`
- `get_endpoint_docs`
- `call_api`
- `query_data`

Built-in apply functions defined in `functions.py`:

- `simple_return`
- `log_return`
- `sma`
- `ema`
- `spread`

## Known Issues And TODOs

- Runtime startup does not use `parser.py`, `tradermade-full.txt`, `test_parser_inline.py`, or `MCP_AVAILABLE_RESOURCES.py`. The server loads `endpoint_catalog.json` directly.
- `PROJECT_STRUCTURE.md` and `MCP_AVAILABLE_RESOURCES.py` describe a parser-driven startup flow that does not match `src/tradermade_mcp/server.py`.
- `.env` files are not auto-loaded by `src/tradermade_mcp/server.py`. The root bootstrap launcher `run_tradermade_mcp.py` now handles simple `.env` loading itself.
- The test files are standalone scripts, not an integrated `pytest` suite.
