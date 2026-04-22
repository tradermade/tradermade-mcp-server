#!/usr/bin/env python3
"""Quick test of the TraderMade MCP server tools."""

import asyncio
import os
from tradermade_mcp.server import search_endpoints, get_endpoint_docs, call_api, query_data

async def test():
    print("=" * 60)
    print("Testing TraderMade MCP Server")
    print("=" * 60)

    # Test 1: Search endpoints
    print("\n1. Testing search_endpoints (query='live rates')...")
    result = await search_endpoints(query="live rates")
    print(result[:500])

    # Test 2: Get endpoint docs
    print("\n2. Testing get_endpoint_docs (url='live')...")
    result = await get_endpoint_docs(url="live")
    print(result[:500])

    # Test 3: Call API - get live quotes
    print("\n3. Testing call_api (GET /live with EURUSD)...")
    result = await call_api(
        method="GET",
        path="/live",
        params={"currency": "EURUSD"}
    )
    print(result[:500] if len(result) > 500 else result)

    # Test 4: Search functions
    print("\n4. Testing search_endpoints with functions (scope='functions')...")
    result = await search_endpoints(query="moving average", scope="functions")
    print(result[:500])

    print("\n" + "=" * 60)
    print("[OK] All basic tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    # Set up API key from env
    if not os.getenv("TRADERMADE_API_KEY"):
        print("⚠️  Note: TRADERMADE_API_KEY not set, some tests may fail")

    asyncio.run(test())
