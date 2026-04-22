"""Component registrations for TraderMade MCP."""

from .analytics import (
    WORKFLOW_DOCS,
    WorkflowDoc,
    format_workflow_docs,
    format_workflow_search_result,
    register_analytics_tools,
    resolve_workflow_tool,
    search_workflow_tools,
)
from .indicators import (
    INDICATOR_DOCS,
    IndicatorDoc,
    format_indicator_docs,
    format_indicator_search_result,
    register_indicator_tools,
    resolve_indicator_tool,
    search_indicator_tools,
)

__all__ = [
    "WORKFLOW_DOCS",
    "WorkflowDoc",
    "format_workflow_docs",
    "format_workflow_search_result",
    "register_analytics_tools",
    "resolve_workflow_tool",
    "search_workflow_tools",
    "INDICATOR_DOCS",
    "IndicatorDoc",
    "format_indicator_docs",
    "format_indicator_search_result",
    "register_indicator_tools",
    "resolve_indicator_tool",
    "search_indicator_tools",
]
