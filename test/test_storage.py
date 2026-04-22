#!/usr/bin/env python3
"""Test the data storage and SQL query features."""

import asyncio
import os
from tradermade_mcp.server import call_api, query_data

async def test_storage():
    print("=" * 60)
    print("Testing Data Storage & SQL Queries")
    print("=" * 60)

    # Test 1: Store data
    print("\n1. Fetching and storing EURUSD live data...")
    result = await call_api(
        method="GET",
        path="/live",
        params={"currency": "EURUSD,GBPUSD,USDJPY"},
        store_as="fx_quotes"
    )
    print(result)

    # Test 2: Show tables
    print("\n2. Listing stored tables...")
    result = await query_data(sql="SHOW TABLES")
    print(result)

    # Test 3: Describe table
    print("\n3. Describing fx_quotes table...")
    result = await query_data(sql="DESCRIBE fx_quotes")
    print(result)

    # Test 4: Query the data
    print("\n4. Querying stored data...")
    result = await query_data(
        sql="SELECT base_currency, quote_currency, bid, ask, mid FROM fx_quotes"
    )
    print(result)

    # Test 5: Query with post-processing (SMA)
    print("\n5. Querying data with post-processing (computing spread)...")
    result = await query_data(
        sql="SELECT base_currency, quote_currency, bid, ask FROM fx_quotes",
        apply=[
            {
                "function": "spread",
                "inputs": {"bid_column": "bid", "ask_column": "ask"},
                "output": "spread"
            }
        ]
    )
    print(result)

    print("\n" + "=" * 60)
    print("[OK] Storage and query tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    if not os.getenv("TRADERMADE_API_KEY"):
        print("[Warning] TRADERMADE_API_KEY not set")

    asyncio.run(test_storage())
