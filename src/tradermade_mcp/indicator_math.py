"""
Technical Analysis Indicators — built from scratch (no TA-Lib).
Implements: RSI, MACD, SMA, EMA, BBANDS, ATR, STOCH, ADX
"""

import math


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _validate(data: list, name: str = "data", min_len: int = 2):
    if not isinstance(data, list) or len(data) < min_len:
        raise ValueError(f"'{name}' must be a list with at least {min_len} values.")
    for i, v in enumerate(data):
        if not isinstance(v, (int, float)) or math.isnan(v):
            raise ValueError(f"'{name}[{i}]' is not a valid number.")


def _safe(value: float, decimals: int = 4):
    """Return rounded float or None if NaN/Inf."""
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return round(value, decimals)


# ─────────────────────────────────────────────────────────────────────────────
# 1. SMA — Simple Moving Average
# ─────────────────────────────────────────────────────────────────────────────

def calculate_sma(close: list, timeperiod: int = 20) -> dict:
    """
    Simple Moving Average.
    Formula: SMA[i] = mean(close[i - period + 1 : i + 1])
    """
    _validate(close, "close", min_len=timeperiod)

    values = []
    for i in range(len(close)):
        if i < timeperiod - 1:
            values.append(None)
        else:
            window = close[i - timeperiod + 1 : i + 1]
            values.append(_safe(sum(window) / timeperiod))

    latest = values[-1]
    price  = close[-1]

    return {
        "indicator":  "SMA",
        "timeperiod": timeperiod,
        "values":     values,
        "latest":     latest,
        "price_vs_sma": (
            "above" if latest is not None and price > latest else
            "below" if latest is not None and price < latest else
            "at"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. EMA — Exponential Moving Average
# ─────────────────────────────────────────────────────────────────────────────

def calculate_ema(close: list, timeperiod: int = 20) -> dict:
    """
    Exponential Moving Average.
    k      = 2 / (period + 1)
    EMA[0] = SMA of first `period` bars
    EMA[i] = close[i] * k + EMA[i-1] * (1 - k)
    """
    _validate(close, "close", min_len=timeperiod)

    k      = 2.0 / (timeperiod + 1)
    values = [None] * (timeperiod - 1)

    # seed with first SMA
    seed = sum(close[:timeperiod]) / timeperiod
    values.append(_safe(seed))

    ema = seed
    for price in close[timeperiod:]:
        ema = price * k + ema * (1 - k)
        values.append(_safe(ema))

    latest = values[-1]
    price  = close[-1]

    return {
        "indicator":  "EMA",
        "timeperiod": timeperiod,
        "values":     values,
        "latest":     latest,
        "price_vs_ema": (
            "above" if latest is not None and price > latest else
            "below" if latest is not None and price < latest else
            "at"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. RSI — Relative Strength Index
# ─────────────────────────────────────────────────────────────────────────────

def calculate_rsi(close: list, timeperiod: int = 14) -> dict:
    """
    Relative Strength Index (Wilder smoothing).
    RS     = avg_gain / avg_loss  (over `timeperiod` bars)
    RSI    = 100 - 100 / (1 + RS)
    First avg_gain/loss = simple mean of first `period` changes.
    Subsequent = (prev_avg * (period-1) + current) / period  (Wilder)
    """
    _validate(close, "close", min_len=timeperiod + 1)

    deltas = [close[i] - close[i - 1] for i in range(1, len(close))]

    gains  = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]

    # seed averages
    avg_gain = sum(gains[:timeperiod]) / timeperiod
    avg_loss = sum(losses[:timeperiod]) / timeperiod

    values = [None] * (timeperiod)  # first `timeperiod` closes have no RSI

    def _rsi(ag, al):
        if al == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    values.append(_safe(_rsi(avg_gain, avg_loss)))

    for i in range(timeperiod, len(deltas)):
        avg_gain = (avg_gain * (timeperiod - 1) + gains[i])  / timeperiod
        avg_loss = (avg_loss * (timeperiod - 1) + losses[i]) / timeperiod
        values.append(_safe(_rsi(avg_gain, avg_loss)))

    latest = values[-1]

    return {
        "indicator":  "RSI",
        "timeperiod": timeperiod,
        "values":     values,
        "latest":     latest,
        "signal": (
            "overbought" if latest is not None and latest > 70 else
            "oversold"   if latest is not None and latest < 30 else
            "neutral"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. MACD — Moving Average Convergence/Divergence
# ─────────────────────────────────────────────────────────────────────────────

def calculate_macd(
    close: list,
    fastperiod: int = 12,
    slowperiod: int = 26,
    signalperiod: int = 9,
) -> dict:
    """
    MACD Line   = EMA(fast) - EMA(slow)
    Signal Line = EMA(MACD, signal_period)
    Histogram   = MACD - Signal
    """
    _validate(close, "close", min_len=slowperiod + signalperiod)

    def _ema_series(data, period):
        k      = 2.0 / (period + 1)
        result = [None] * (period - 1)
        seed   = sum(data[:period]) / period
        result.append(seed)
        ema = seed
        for p in data[period:]:
            ema = p * k + ema * (1 - k)
            result.append(ema)
        return result

    fast_ema = _ema_series(close, fastperiod)
    slow_ema = _ema_series(close, slowperiod)

    # MACD line (aligned to slow EMA length)
    macd_line = []
    for f, s in zip(fast_ema, slow_ema):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(f - s)

    # Signal line = EMA of MACD values (skip Nones)
    macd_valid = [v for v in macd_line if v is not None]
    signal_raw = _ema_series(macd_valid, signalperiod)

    # Re-pad signal to full length
    none_count  = len(macd_line) - len(macd_valid)
    signal_line = [None] * (none_count + signalperiod - 1) + [
        v for v in signal_raw if v is not None
    ]
    # Pad if lengths differ
    while len(signal_line) < len(macd_line):
        signal_line.insert(0, None)

    histogram = []
    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)

    macd_latest = macd_line[-1]
    sig_latest  = signal_line[-1]
    hist_latest = histogram[-1]
    macd_latest_safe = _safe(macd_latest)
    sig_latest_safe = _safe(sig_latest)
    hist_latest_safe = _safe(hist_latest)

    return {
        "indicator":  "MACD",
        "fastperiod": fastperiod,
        "slowperiod": slowperiod,
        "signalperiod": signalperiod,
        "macd":      macd_latest_safe,
        "signal":    sig_latest_safe,
        "histogram": hist_latest_safe,
        "crossover": (
            "bullish" if hist_latest_safe is not None and hist_latest_safe > 0 else
            "bearish" if hist_latest_safe is not None and hist_latest_safe < 0 else
            "flat"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. BBANDS — Bollinger Bands
# ─────────────────────────────────────────────────────────────────────────────

def calculate_bbands(
    close: list,
    timeperiod: int = 20,
    nbdevup: float  = 2.0,
    nbdevdn: float  = 2.0,
) -> dict:
    """
    Middle = SMA(close, period)
    Std    = population std-dev of window
    Upper  = Middle + nbdevup * Std
    Lower  = Middle - nbdevdn * Std
    """
    _validate(close, "close", min_len=timeperiod)

    upper_band  = []
    middle_band = []
    lower_band  = []

    for i in range(len(close)):
        if i < timeperiod - 1:
            upper_band.append(None)
            middle_band.append(None)
            lower_band.append(None)
        else:
            window = close[i - timeperiod + 1 : i + 1]
            mean   = sum(window) / timeperiod
            var    = sum((x - mean) ** 2 for x in window) / timeperiod
            std    = math.sqrt(var)

            middle_band.append(_safe(mean))
            upper_band.append(_safe(mean + nbdevup * std))
            lower_band.append(_safe(mean - nbdevdn * std))

    upper  = upper_band[-1]
    middle = middle_band[-1]
    lower  = lower_band[-1]
    price  = close[-1]

    bandwidth = (
        _safe((upper - lower) / middle * 100)
        if upper is not None and middle not in (None, 0) and lower is not None
        else None
    )

    return {
        "indicator":  "BBANDS",
        "timeperiod": timeperiod,
        "upper":      upper,
        "middle":     middle,
        "lower":      lower,
        "bandwidth":  bandwidth,
        "upper_values":  upper_band,
        "middle_values": middle_band,
        "lower_values":  lower_band,
        "position": (
            "above_upper" if upper is not None and price > upper else
            "below_lower" if lower is not None and price < lower else
            "inside"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. ATR — Average True Range
# ─────────────────────────────────────────────────────────────────────────────

def calculate_atr(high: list, low: list, close: list, timeperiod: int = 14) -> dict:
    """
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR[0]     = simple mean of first `period` TRs
    ATR[i]     = (ATR[i-1] * (period-1) + TR[i]) / period  (Wilder)
    """
    _validate(high,  "high",  min_len=timeperiod + 1)
    _validate(low,   "low",   min_len=timeperiod + 1)
    _validate(close, "close", min_len=timeperiod + 1)

    tr_values = []
    for i in range(1, len(close)):
        hl  = high[i]  - low[i]
        hpc = abs(high[i]  - close[i - 1])
        lpc = abs(low[i]   - close[i - 1])
        tr_values.append(max(hl, hpc, lpc))

    # seed
    atr    = sum(tr_values[:timeperiod]) / timeperiod
    values = [None] * timeperiod  # align with close length (index 0 = close[0])
    values.append(_safe(atr))

    for tr in tr_values[timeperiod:]:
        atr = (atr * (timeperiod - 1) + tr) / timeperiod
        values.append(_safe(atr))

    latest = values[-1]

    return {
        "indicator":  "ATR",
        "timeperiod": timeperiod,
        "values":     values,
        "latest":     latest,
        "suggested_stop_pct": (
            _safe(latest / close[-1] * 100) if latest is not None and close[-1] != 0 else None
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. STOCH — Stochastic Oscillator
# ─────────────────────────────────────────────────────────────────────────────

def calculate_stoch(
    high: list,
    low:  list,
    close: list,
    fastk_period: int = 5,
    slowk_period: int = 3,
    slowd_period: int = 3,
) -> dict:
    """
    %K (fast) = (close - lowest_low) / (highest_high - lowest_low) * 100
    Slow %K   = SMA(%K_fast, slowk_period)
    Slow %D   = SMA(Slow %K,  slowd_period)
    """
    _validate(high,  "high",  min_len=fastk_period)
    _validate(low,   "low",   min_len=fastk_period)
    _validate(close, "close", min_len=fastk_period)

    # Fast %K
    fastk = []
    for i in range(len(close)):
        if i < fastk_period - 1:
            fastk.append(None)
        else:
            h = max(high[i - fastk_period + 1 : i + 1])
            l = min(low[i  - fastk_period + 1 : i + 1])
            if h == l:
                fastk.append(0.0)
            else:
                fastk.append((close[i] - l) / (h - l) * 100.0)

    # Slow %K = SMA of fast %K
    def _sma_of(series, period):
        out = []
        valid = [(i, v) for i, v in enumerate(series) if v is not None]
        for idx, (orig_i, _) in enumerate(valid):
            if idx < period - 1:
                out.append((orig_i, None))
            else:
                window = [v for _, v in valid[idx - period + 1 : idx + 1]]
                out.append((orig_i, sum(window) / period))
        result = [None] * len(series)
        for orig_i, val in out:
            result[orig_i] = _safe(val) if val is not None else None
        return result

    slowk = _sma_of(fastk, slowk_period)
    slowd = _sma_of(slowk, slowd_period)

    sk_latest = slowk[-1]
    sd_latest = slowd[-1]

    return {
        "indicator":    "STOCH",
        "fastk_period": fastk_period,
        "slowk_period": slowk_period,
        "slowd_period": slowd_period,
        "slowk":        sk_latest,
        "slowd":        sd_latest,
        "slowk_values": slowk,
        "slowd_values": slowd,
        "signal": (
            "overbought" if sk_latest is not None and sk_latest > 80 else
            "oversold"   if sk_latest is not None and sk_latest < 20 else
            "neutral"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. ADX — Average Directional Index
# ─────────────────────────────────────────────────────────────────────────────

def calculate_adx(high: list, low: list, close: list, timeperiod: int = 14) -> dict:
    """
    +DM = high[i] - high[i-1]  if > 0 and > -(low[i]-low[i-1]) else 0
    -DM = low[i-1] - low[i]    if > 0 and > +(high[i]-high[i-1]) else 0
    TR  = max(high-low, |high-prev_close|, |low-prev_close|)

    Smoothed (Wilder):
      ATR14, +DI14, -DI14
      DX    = 100 * |+DI - -DI| / (+DI + -DI)
      ADX   = Wilder smooth of DX
    """
    _validate(high,  "high",  min_len=2 * timeperiod + 1)
    _validate(low,   "low",   min_len=2 * timeperiod + 1)
    _validate(close, "close", min_len=2 * timeperiod + 1)

    tr_list, pdm_list, ndm_list = [], [], []

    for i in range(1, len(close)):
        hl  = high[i]  - low[i]
        hpc = abs(high[i]  - close[i - 1])
        lpc = abs(low[i]   - close[i - 1])
        tr_list.append(max(hl, hpc, lpc))

        up   = high[i]  - high[i - 1]
        down = low[i - 1] - low[i]

        pdm_list.append(up   if up   > down and up   > 0 else 0.0)
        ndm_list.append(down if down > up   and down > 0 else 0.0)

    # Wilder smooth seed
    atr  = sum(tr_list[:timeperiod])
    pdm  = sum(pdm_list[:timeperiod])
    ndm  = sum(ndm_list[:timeperiod])

    dx_values = []

    def _dx(p, n, t):
        pdi = 100.0 * p / t if t else 0.0
        ndi = 100.0 * n / t if t else 0.0
        denom = pdi + ndi
        return 100.0 * abs(pdi - ndi) / denom if denom else 0.0

    dx_values.append(_dx(pdm, ndm, atr))

    for i in range(timeperiod, len(tr_list)):
        atr = atr - atr / timeperiod + tr_list[i]
        pdm = pdm - pdm / timeperiod + pdm_list[i]
        ndm = ndm - ndm / timeperiod + ndm_list[i]
        dx_values.append(_dx(pdm, ndm, atr))

    # ADX = Wilder smooth of DX
    adx = sum(dx_values[:timeperiod]) / timeperiod
    adx_values = [None] * (len(close) - len(dx_values) + timeperiod - 1)
    adx_values.append(_safe(adx))

    for dx in dx_values[timeperiod:]:
        adx = (adx * (timeperiod - 1) + dx) / timeperiod
        adx_values.append(_safe(adx))

    latest = adx_values[-1]

    # +DI / -DI for last bar
    pdi_last = _safe(100.0 * pdm / atr) if atr else None
    ndi_last = _safe(100.0 * ndm / atr) if atr else None

    return {
        "indicator":    "ADX",
        "timeperiod":   timeperiod,
        "values":       adx_values,
        "latest":       latest,
        "plus_di":      pdi_last,
        "minus_di":     ndi_last,
        "trend_strength": (
            "very strong" if latest is not None and latest > 50 else
            "strong"      if latest is not None and latest > 25 else
            "weak/ranging"
        ),
        "direction": (
            "bullish" if pdi_last is not None and ndi_last is not None and pdi_last > ndi_last else
            "bearish" if pdi_last is not None and ndi_last is not None and ndi_last > pdi_last else
            "unclear"
        ),
    }
