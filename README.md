# TraderMade MCP Server

Connect MCP-capable AI clients directly to TraderMade's financial data. Built with Python and FastMCP, this server gives AI agents the tools to discover endpoints, fetch live and historical market data, run SQL over stored results, compute technical indicators, and execute higher-level analytics workflows — all inside a single MCP session.

**Requirements:** Python 3.10+ and a [TraderMade API key](https://tradermade.com/signup).

---

## Setup

### One-command setup (recommended)

The bootstrap script creates a virtual environment, installs all dependencies, and writes your Claude Desktop config automatically — no manual JSON editing required.

**Windows:**
```powershell
.\run_tradermade_mcp.cmd --api-key=YOUR_TRADERMADE_API_KEY --bootstrap-only --configure-claude
```

**macOS/Linux:**
```bash
python run_tradermade_mcp.py --api-key=YOUR_TRADERMADE_API_KEY --bootstrap-only --configure-claude
```

When it finishes you will see:
```
[tradermade-bootstrap] Bootstrap complete
[tradermade-bootstrap] Claude Desktop config written → .../claude_desktop_config.json
[tradermade-bootstrap] Restart Claude Desktop to apply the new server configuration.
```

Fully restart Claude Desktop, click **+** near the chat input, open **Connectors**, and confirm **tradermade** appears in the list. Done.

---

### Manual setup

If you prefer to manage the config yourself, run bootstrap without `--configure-claude`:

**Windows:**
```powershell
.\run_tradermade_mcp.cmd --api-key=YOUR_TRADERMADE_API_KEY --bootstrap-only
```

**macOS/Linux:**
```bash
python run_tradermade_mcp.py --api-key=YOUR_TRADERMADE_API_KEY --bootstrap-only
```

Then open **Claude Desktop → Settings → Developer → Edit Config** and add the block below. If a `mcpServers` key already exists, only add the `tradermade` entry inside it.

**Windows:**
```json
{
  "mcpServers": {
    "tradermade": {
      "command": "C:\\path\\to\\repo\\venv\\Scripts\\python.exe",
      "args": ["-m", "tradermade_mcp.server"],
      "env": {
        "TRADERMADE_API_KEY": "YOUR_TRADERMADE_API_KEY"
      }
    }
  }
}
```

> Replace `C:\path\to\repo` with your actual folder path, for example `C:\Users\DIRECTORYNAME\Desktop\tradermade-mcp-server`. Use double backslashes throughout.

**macOS/Linux:**
```json
{
  "mcpServers": {
    "tradermade": {
      "command": "/path/to/repo/venv/bin/python",
      "args": ["-m", "tradermade_mcp.server"],
      "env": {
        "TRADERMADE_API_KEY": "YOUR_TRADERMADE_API_KEY"
      }
    }
  }
}
```

Save, fully restart Claude Desktop, and verify under **Connectors**.

---

### Claude Code

After bootstrapping the repo:

**Windows:**
```powershell
claude mcp add tradermade --scope user --env TRADERMADE_API_KEY=YOUR_TRADERMADE_API_KEY -- C:\path\to\repo\venv\Scripts\python.exe -m tradermade_mcp.server
```

**macOS/Linux:**
```bash
claude mcp add tradermade --scope user --env TRADERMADE_API_KEY=YOUR_TRADERMADE_API_KEY -- /path/to/repo/venv/bin/python -m tradermade_mcp.server
```

---

### API key options

You can provide your API key in any of three ways — the launcher picks up whichever is present:

- Pass it on the command line: `--api-key=YOUR_KEY`
- Set it in a project-root `.env` file: `TRADERMADE_API_KEY=YOUR_KEY`
- Set it in your MCP client config under `env`

---

## What the server can do

### Endpoint discovery

Before making a call the agent can search for the correct TraderMade endpoint or local component and inspect its parameter documentation. This removes guesswork about endpoint names and required fields, and means the agent gets requests right on the first try.

### Live and historical market data

`call_api` covers the full TraderMade catalog:

- Live FX, crypto, and CFD spot quotes
- Historical daily OHLC data
- Minute, hourly, and custom timeseries data
- Historical tick and sample tick data
- Currency, crypto, and CFD reference lists
- Conversion and market-status endpoints

### SQL over stored results

When the agent fetches tabular data, results can be stored in a local SQLite database named `tradermade_cache.sqlite` by default. The agent then runs read-only SQL for follow-up analysis without re-fetching — useful for:

- Comparing multiple instruments side-by-side
- Filtering a timeseries by date range or symbol
- Calculating custom summaries over cached datasets

Set `TRADERMADE_SQLITE_PATH` or pass `--sqlite-path` to override the cache file location.

### Technical indicators

Local indicator components run calculations directly inside the MCP workflow, without an external analysis stack:

| Indicator | Component |
|-----------|-----------|
| Simple Moving Average | `get_sma` |
| Exponential Moving Average | `get_ema` |
| Relative Strength Index | `get_rsi` |
| MACD | `get_macd` |
| Bollinger Bands | `get_bbands` |
| Average True Range | `get_atr` |
| Stochastic Oscillator | `get_stoch` |
| Average Directional Index | `get_adx` |

### Analytics workflows

Higher-level tools for complex prompts:

- **`analyze_markets`** — multi-market comparison with summary table, range table, pivot table, and consolidated chart output
- **`validate_market_csv`** — reconcile an internal OHLC CSV against TraderMade historical data
- **`analyze_trade_tca`** — transaction cost analysis using tick data, with automatic minute-bar fallback

### Built-in query functions

The SQL pipeline also supports row-level post-processing functions:

- `simple_return`
- `log_return`
- `sma`
- `ema`
- `spread`

---

## Core MCP tools

| Tool | What it does |
|------|-------------|
| `search_endpoints` | Search TraderMade endpoints, indicator components, analytics workflows, and post-processing functions |
| `get_endpoint_docs` | Get parameter help for a TraderMade endpoint |
| `get_component_docs` | Get parameter help for a local indicator or analytics component |
| `call_api` | Call allow-listed TraderMade REST endpoints |
| `query_data` | Run read-only SQL over stored tabular results |

---

## Manual transport modes

The default transport is `stdio`, which is what local MCP clients use. For HTTP-based testing or hosting:

```bash
python run_tradermade_mcp.py --transport streamable-http --api-key YOUR_TRADERMADE_API_KEY
```

```bash
python run_tradermade_mcp.py --transport sse --api-key YOUR_TRADERMADE_API_KEY
```

> Running the launcher without `--bootstrap-only` bootstraps the environment and starts the server in stdio mode. This looks silent in a terminal because it is waiting for an MCP client to connect — that is expected behaviour.

---

## Project layout

```
src/tradermade_mcp/
  server.py                  Main MCP server entry point
  endpoint_catalog.json      TraderMade endpoint catalog used by discovery and docs
  endpoint_index.py          Endpoint search and resolution logic
  store.py                   Persistent SQLite store
  functions.py               Built-in row/query post-processing functions
  indicator_math.py          Local technical indicator calculation engine
  components/
    indicators.py            Indicator MCP tool registration
    analytics.py             Higher-level analytics workflow tools

run_tradermade_mcp.py        Cross-platform bootstrap launcher
run_tradermade_mcp.cmd       Windows bootstrap wrapper
```

---

## Testing

```bash
python test_mcp.py              # Basic server-tool checks
python test_storage.py          # Storage and SQL workflow checks
python test_parser_inline.py    # Parser and catalog checks against tradermade-full.txt
```

These are manual scripts, not a full pytest suite.

---

## License

See [LICENSE](LICENSE).
