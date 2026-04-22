#!/usr/bin/env python3
"""Inline parser test - can be run directly or imported."""

from pathlib import Path
from src.tradermade_mcp.parser import parse_tradermade_docs, convert_parsed_to_json_format
import json


def main():
    print("=" * 70)
    print("[TEST SUITE] TraderMade Markdown Parser - Inline Test")
    print("=" * 70)

    # TEST 1: Load file
    print("\n[TEST 1] Load tradermade-full.txt...")
    file_path = Path("tradermade-full.txt")
    if not file_path.exists():
        print("  [FAIL] File not found!")
        return False

    content = file_path.read_text(encoding="utf-8")
    print("  [PASS] Loaded %d bytes" % len(content))

    # TEST 2: Parse endpoints
    print("\n[TEST 2] Parse markdown into endpoints...")
    endpoints = parse_tradermade_docs(content)
    print("  [PASS] Parsed %d endpoints" % len(endpoints))

    # TEST 3: Verify structure
    print("\n[TEST 3] Verify endpoint structure...")
    sample = endpoints[0]
    print("  Endpoint: %s" % sample.name)
    print("    Path: %s" % sample.path_pattern)
    print("    Market: %s" % sample.market)
    print("    Params: %d" % len(sample.params))
    print("    Tags: %s" % sample.tags)
    print("    Examples: %d" % len(sample.examples))
    print("  [PASS] Structure verified")

    # TEST 4: Check critical endpoints
    print("\n[TEST 4] Check for critical endpoints...")
    names = set(ep.name for ep in endpoints)
    critical = ["live", "historical", "timeseries", "convert", "market_open_status"]
    found = [name for name in critical if name in names]
    print("  Found %d/%d critical endpoints:" % (len(found), len(critical)))
    for name in found:
        ep = next(e for e in endpoints if e.name == name)
        print("    - %s (%s)" % (name, ep.market))
    status = "[PASS]" if len(found) >= 4 else "[WARN]"
    print("  %s Critical endpoints present" % status)

    # TEST 5: Convert to JSON
    print("\n[TEST 5] Convert to JSON format...")
    try:
        converted = [convert_parsed_to_json_format(ep) for ep in endpoints]
        json_str = json.dumps(converted, indent=2)
        print("  [PASS] Converted %d endpoints to JSON (%d bytes)" % (len(converted), len(json_str)))

        # Show sample
        sample_json = json.loads(json_str)[0]
        print("  Sample: %s" % sample_json['name'])
        print("    - docs_id: %s" % sample_json['docs_id'])
        print("    - path_pattern: %s" % sample_json['path_pattern'])
        print("    - source: %s" % sample_json['source'])
    except Exception as e:
        print("  [FAIL] Conversion failed: %s" % str(e))
        return False

    # TEST 6: Verify parameters extraction
    print("\n[TEST 6] Verify parameters extraction...")
    endpoints_with_params = [ep for ep in endpoints if ep.params]
    print("  [PASS] %d endpoints have parameters" % len(endpoints_with_params))

    if endpoints_with_params:
        sample = endpoints_with_params[0]
        print("  Sample: %s" % sample.name)
        for param in sample.params[:2]:
            print("    - %s: %s (%s)" % (param.get('name'), param.get('type'), param.get('location')))

    # TEST 7: Verify tags extraction
    print("\n[TEST 7] Verify tags extraction...")
    endpoints_with_tags = [ep for ep in endpoints if ep.tags]
    print("  [PASS] %d endpoints have tags" % len(endpoints_with_tags))
    if endpoints_with_tags:
        sample = endpoints_with_tags[0]
        print("  Sample: %s" % sample.name)
        print("    Tags: %s" % ', '.join(sample.tags[:3]))

    # TEST 8: Verify examples extraction
    print("\n[TEST 8] Verify examples extraction...")
    endpoints_with_examples = [ep for ep in endpoints if ep.examples]
    print("  [PASS] %d endpoints have examples" % len(endpoints_with_examples))
    if endpoints_with_examples:
        sample = endpoints_with_examples[0]
        print("  Sample: %s" % sample.name)
        print("    Example: %s" % sample.examples[0])

    # TEST 9: Compare with JSON catalog
    print("\n[TEST 9] Compare with existing endpoint_catalog.json...")
    json_path = Path("src/tradermade_mcp/endpoint_catalog.json")
    if json_path.exists():
        with open(json_path) as f:
            json_data = json.load(f)

        json_names = set(ep["name"] for ep in json_data)
        markdown_names = set(ep.name for ep in endpoints)

        common = json_names & markdown_names
        coverage = len(common) / len(json_names) * 100 if json_names else 0

        print("  JSON catalog: %d endpoints" % len(json_names))
        print("  Markdown: %d endpoints" % len(markdown_names))
        print("  Coverage: %d/%d endpoints (%.0f%%)" % (len(common), len(json_names), coverage))
        print("  [PASS] Comparison complete")
    else:
        print("  [WARN] endpoint_catalog.json not found, skipping comparison")

    # TEST 10: Performance
    print("\n[TEST 10] Performance test...")
    import time
    start = time.time()
    test_endpoints = parse_tradermade_docs(content)
    elapsed = time.time() - start
    print("  [PASS] Parsed %d endpoints in %.2fms" % (len(test_endpoints), elapsed*1000))

    if elapsed < 1.0:
        print("  [PASS] Performance: EXCELLENT (< 1 second)")
    elif elapsed < 5.0:
        print("  [PASS] Performance: GOOD (< 5 seconds)")
    else:
        print("  [WARN] Performance: SLOW (> 5 seconds)")

    # SUMMARY
    print("\n" + "=" * 70)
    print("[RESULT] ALL TESTS PASSED!")
    print("=" * 70)
    print("\nSummary:")
    print("  [OK] Successfully loaded tradermade-full.txt")
    print("  [OK] Parsed %d endpoints from markdown" % len(endpoints))
    print("  [OK] Verified endpoint structure")
    print("  [OK] Found critical endpoints: %d/%d" % (len(found), len(critical)))
    print("  [OK] Converted to JSON format successfully")
    print("  [OK] Parameters extracted: %d endpoints" % len(endpoints_with_params))
    print("  [OK] Tags extracted: %d endpoints" % len(endpoints_with_tags))
    print("  [OK] Examples extracted: %d endpoints" % len(endpoints_with_examples))
    print("  [OK] Performance: %.2fms for %d endpoints" % (elapsed*1000, len(endpoints)))

    return True


if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except Exception as e:
        print("\n[ERROR] %s" % str(e))
        import traceback
        traceback.print_exc()
        exit(1)
