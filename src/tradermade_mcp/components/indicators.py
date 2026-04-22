from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from ..indicator_math import (
    calculate_adx,
    calculate_atr,
    calculate_bbands,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
    calculate_stoch,
)


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_+.-]+")


@dataclass(frozen=True)
class IndicatorDoc:
    tool_name: str
    indicator: str
    category: str
    description: str
    params: tuple[str, ...]
    tags: tuple[str, ...] = ()

    def search_text(self) -> str:
        return " ".join(
            [self.tool_name, self.indicator, self.category, self.description, *self.params, *self.tags]
        ).lower()

    def full_description(self) -> str:
        params = ", ".join(self.params)
        return f"{self.description} Inputs: {params}."


INDICATOR_DOCS: tuple[IndicatorDoc, ...] = (
    IndicatorDoc(
        tool_name="get_sma",
        indicator="SMA",
        category="indicator-component",
        description="Simple moving average over a close-price series.",
        params=("close", "timeperiod"),
        tags=("moving average", "trend", "component", "technical analysis"),
    ),
    IndicatorDoc(
        tool_name="get_ema",
        indicator="EMA",
        category="indicator-component",
        description="Exponential moving average over a close-price series.",
        params=("close", "timeperiod"),
        tags=("moving average", "trend", "component", "technical analysis"),
    ),
    IndicatorDoc(
        tool_name="get_rsi",
        indicator="RSI",
        category="indicator-component",
        description="Relative Strength Index with overbought and oversold signal output.",
        params=("close", "timeperiod"),
        tags=("momentum", "oscillator", "component", "technical analysis"),
    ),
    IndicatorDoc(
        tool_name="get_macd",
        indicator="MACD",
        category="indicator-component",
        description="MACD line, signal line, histogram, and bullish or bearish crossover state.",
        params=("close", "fastperiod", "slowperiod", "signalperiod"),
        tags=("momentum", "trend", "component", "technical analysis"),
    ),
    IndicatorDoc(
        tool_name="get_bbands",
        indicator="BBANDS",
        category="indicator-component",
        description="Bollinger Bands with upper, middle, lower bands, bandwidth, and price position.",
        params=("close", "timeperiod", "nbdevup", "nbdevdn"),
        tags=("volatility", "bands", "component", "technical analysis"),
    ),
    IndicatorDoc(
        tool_name="get_atr",
        indicator="ATR",
        category="indicator-component",
        description="Average True Range with suggested stop percentage from price.",
        params=("high", "low", "close", "timeperiod"),
        tags=("volatility", "risk", "component", "technical analysis"),
    ),
    IndicatorDoc(
        tool_name="get_stoch",
        indicator="STOCH",
        category="indicator-component",
        description="Slow stochastic oscillator with slow %K, slow %D, and signal state.",
        params=("high", "low", "close", "fastk_period", "slowk_period", "slowd_period"),
        tags=("momentum", "oscillator", "component", "technical analysis"),
    ),
    IndicatorDoc(
        tool_name="get_adx",
        indicator="ADX",
        category="indicator-component",
        description="Average Directional Index with trend strength, +DI, -DI, and direction.",
        params=("high", "low", "close", "timeperiod"),
        tags=("trend strength", "directional movement", "component", "technical analysis"),
    ),
)


def search_indicator_tools(query: str, top_k: int = 5) -> list[IndicatorDoc]:
    tokens = _tokenize(query)
    lowered = query.strip().lower()
    scored: list[tuple[float, IndicatorDoc]] = []
    for doc in INDICATOR_DOCS:
        score = 0.0
        haystack = doc.search_text()
        if lowered in {doc.tool_name.lower(), doc.indicator.lower()}:
            score += 50.0
        if doc.tool_name.lower() in lowered:
            score += 18.0
        if doc.indicator.lower() in lowered:
            score += 18.0
        if doc.category in lowered:
            score += 8.0
        for token in tokens:
            if token in {doc.tool_name.lower(), doc.indicator.lower()}:
                score += 12.0
            if token in haystack:
                score += 2.5
            if any(token == tag.lower() for tag in doc.tags):
                score += 5.0
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda item: (-item[0], item[1].tool_name))
    return [doc for _, doc in scored[:top_k]]


def format_indicator_search_result(doc: IndicatorDoc, rank: int) -> str:
    return f"{rank}. {doc.indicator} via {doc.tool_name} [{doc.category}] (component)\n   {doc.full_description()}"


def resolve_indicator_tool(name: str) -> IndicatorDoc | None:
    normalized = name.strip().lower()
    for doc in INDICATOR_DOCS:
        if normalized in {doc.tool_name.lower(), doc.indicator.lower()}:
            return doc
    return None


def format_indicator_docs(doc: IndicatorDoc) -> str:
    params = "\n".join(f"- {param}" for param in doc.params)
    return (
        f"Component: {doc.indicator}\n"
        f"Tool name: {doc.tool_name}\n"
        f"Category: {doc.category}\n"
        f"Description: {doc.description}\n"
        f"Inputs:\n{params}"
    )


def register_indicator_tools(_mcp, readonly_tool: Callable[[], Callable]):
    @readonly_tool()
    def get_sma(close: list[float], timeperiod: int = 20) -> dict:
        """Compute a simple moving average from closing prices."""
        return calculate_sma(close, timeperiod)

    @readonly_tool()
    def get_ema(close: list[float], timeperiod: int = 20) -> dict:
        """Compute an exponential moving average from closing prices."""
        return calculate_ema(close, timeperiod)

    @readonly_tool()
    def get_rsi(close: list[float], timeperiod: int = 14) -> dict:
        """Compute RSI from closing prices."""
        return calculate_rsi(close, timeperiod)

    @readonly_tool()
    def get_macd(
        close: list[float],
        fastperiod: int = 12,
        slowperiod: int = 26,
        signalperiod: int = 9,
    ) -> dict:
        """Compute MACD from closing prices."""
        return calculate_macd(close, fastperiod, slowperiod, signalperiod)

    @readonly_tool()
    def get_bbands(
        close: list[float],
        timeperiod: int = 20,
        nbdevup: float = 2.0,
        nbdevdn: float = 2.0,
    ) -> dict:
        """Compute Bollinger Bands from closing prices."""
        return calculate_bbands(close, timeperiod, nbdevup, nbdevdn)

    @readonly_tool()
    def get_atr(high: list[float], low: list[float], close: list[float], timeperiod: int = 14) -> dict:
        """Compute Average True Range from high, low, and close prices."""
        return calculate_atr(high, low, close, timeperiod)

    @readonly_tool()
    def get_stoch(
        high: list[float],
        low: list[float],
        close: list[float],
        fastk_period: int = 5,
        slowk_period: int = 3,
        slowd_period: int = 3,
    ) -> dict:
        """Compute the slow stochastic oscillator from high, low, and close prices."""
        return calculate_stoch(high, low, close, fastk_period, slowk_period, slowd_period)

    @readonly_tool()
    def get_adx(high: list[float], low: list[float], close: list[float], timeperiod: int = 14) -> dict:
        """Compute ADX from high, low, and close prices."""
        return calculate_adx(high, low, close, timeperiod)

    return (
        get_sma,
        get_ema,
        get_rsi,
        get_macd,
        get_bbands,
        get_atr,
        get_stoch,
        get_adx,
    )


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]
