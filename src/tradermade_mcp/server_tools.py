"""Compatibility wrapper for indicator MCP components."""

from .components.indicators import (
    INDICATOR_DOCS,
    IndicatorDoc,
    format_indicator_docs,
    format_indicator_search_result,
    register_indicator_tools,
    resolve_indicator_tool,
    search_indicator_tools,
)

__all__ = [
    "INDICATOR_DOCS",
    "IndicatorDoc",
    "format_indicator_docs",
    "format_indicator_search_result",
    "register_indicator_tools",
    "resolve_indicator_tool",
    "search_indicator_tools",
]
