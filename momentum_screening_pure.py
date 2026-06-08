#!/usr/bin/env python3
"""L.U.M.U.S.-8 momentum screening PURE Edition.

This module produces *review candidates*, never executable broker orders.  The
live data source (Yahoo Finance through yfinance) is convenient but is not an
exchange-grade market-data feed; every run therefore emits a data-quality
report and records its as-of date and configuration.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from collections import Counter
from typing import Callable, Mapping, Sequence


LOGGER = logging.getLogger("lumus_pure")
US_FALLBACK = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT", "XOM", "COST", "CAT", "LLY", "ORCL"]
JP_TICKERS = [
    "7203.T", "6758.T", "8306.T", "8035.T", "9984.T", "9432.T", "6861.T", "6098.T",
    "4063.T", "6954.T", "7974.T", "6301.T", "4568.T", "6501.T", "7741.T", "7267.T",
    "6273.T", "4543.T", "8058.T", "8001.T", "8031.T", "8053.T", "8002.T", "8316.T",
    "8411.T", "8766.T", "8801.T", "8802.T", "8591.T", "8725.T", "8750.T", "6857.T",
    "6146.T", "6723.T", "6920.T", "7735.T", "6981.T", "6503.T", "6702.T", "6752.T",
    "6506.T", "6965.T", "7729.T", "6869.T", "6971.T", "6315.T", "4062.T", "7701.T",
    "7011.T", "7012.T", "7013.T", "6367.T", "6113.T", "6481.T", "1801.T", "1802.T",
    "1803.T", "1812.T", "1925.T", "1928.T", "1808.T", "1721.T", "5803.T", "5802.T",
    "7201.T", "7269.T", "7270.T", "5401.T", "5713.T", "1605.T", "5020.T", "9101.T",
    "9104.T", "9107.T", "3407.T", "4188.T", "4452.T", "4911.T", "4183.T", "9983.T",
    "3382.T", "7453.T", "3092.T", "4661.T", "4385.T", "2413.T", "4689.T", "4755.T",
    "9735.T", "3659.T", "4307.T", "3088.T", "3064.T", "2802.T", "2502.T", "2503.T",
    "4502.T", "4519.T", "4503.T", "4523.T", "9020.T", "9021.T", "9022.T", "9201.T",
    "9202.T", "9501.T", "9502.T", "9503.T",
]


@dataclass(frozen=True)
class ScreeningConfig:
    history_days: int = 550
    min_observations: int = 274  # 252-day lookback + 21-day skip + current observation
    skip_recent: int = 21
    stale_business_days: int = 5
    max_missing_ratio: float = 0.03
    selected_per_region: int = 6
    max_weight: float = 0.12
    min_weight: float = 0.04
    sector_warning_threshold: int = 4
    total_budget_jpy: int = 4_500_000
    score_momentum_weight: float = 0.55
    score_quality_weight: float = 0.25
    score_low_vol_weight: float = 0.20


def normalize_ticker(ticker: str, region: str | None = None) -> str:
    """Normalize Yahoo symbols without corrupting Japanese ``.T`` suffixes."""
    symbol = str(ticker).strip().upper()
    if region == "JP" or symbol.endswith(".T"):
        core = symbol[:-2] if symbol.endswith(".T") else symbol
        return f"{core}.T"
    return symbol.replace(".", "-")


def get_tickers_lumus(timeout: int = 10) -> tuple[list[str], list[str]]:
    """Build the universe with explicit, logged fallbacks."""
    us: list[str] = []
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        us = [normalize_ticker(x, "US") for x in tables[0]["Symbol"]]
        LOGGER.info("Loaded %d US tickers from Wikipedia", len(us))
    except Exception as exc:
        LOGGER.warning("Wikipedia universe failed: %s", exc)
    if len(us) < 100:
        try:
            url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            frame = pd.read_csv(pd.io.common.StringIO(response.text))
            us = [normalize_ticker(x, "US") for x in frame["Symbol"]]
            LOGGER.info("Loaded %d US tickers from GitHub fallback", len(us))
        except Exception as exc:
            LOGGER.warning("GitHub universe failed: %s", exc)
    if len(us) < 100:
        us = US_FALLBACK.copy()
        LOGGER.warning("Using reduced static US fallback universe (%d symbols)", len(us))
    return sorted(set(us)), sorted(set(JP_TICKERS))


def _extract_close(raw: pd.DataFrame, requested: Sequence[str]) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        for field in ("Close", "Adj Close"):
            if field in raw.columns.get_level_values(0):
                close = raw[field]
                return close.to_frame(requested[0]) if isinstance(close, pd.Series) else close
    for field in ("Close", "Adj Close"):
        if field in raw.columns:
            return raw[[field]].rename(columns={field: requested[0]})
    return pd.DataFrame()


def download_close(tickers: Sequence[str], history_days: int, downloader: Callable | None = None) -> pd.DataFrame:
    """Download closes in chunks so one failed request cannot erase the universe."""
    if downloader is None:
        downloader = yf.download
    parts: list[pd.DataFrame] = []
    for offset in range(0, len(tickers), 100):
        chunk = list(tickers[offset : offset + 100])
        try:
            period = "2y" if history_days > 365 else ("1mo" if history_days <= 31 else "1y")
            raw = downloader(chunk, period=period, auto_adjust=False, progress=False, threads=True)
            close = _extract_close(raw, chunk)
            if not close.empty:
                parts.append(close)
        except Exception as exc:
            LOGGER.error("Price download chunk failed (%s...): %s", chunk[:3], exc)
    if not parts:
        return pd.DataFrame()
    data = pd.concat(parts, axis=1)
    data = data.loc[:, ~data.columns.duplicated()].sort_index()
    return data.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)


def data_quality_gate(prices: pd.DataFrame, tickers: Sequence[str], config: ScreeningConfig, as_of: pd.Timestamp | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reject insufficient/stale series. Only short internal gaps are forward-filled."""
    as_of = pd.Timestamp(as_of or prices.index.max()).normalize() if not prices.empty else pd.Timestamp.today().normalize()
    accepted: dict[str, pd.Series] = {}
    rows = []
    for ticker in tickers:
        reason = "accepted"
        if ticker not in prices.columns:
            rows.append({"Ticker": ticker, "Status": "rejected", "Reason": "not_downloaded", "Observations": 0, "Missing_Ratio": 1.0, "Last_Date": ""})
            continue
        raw = prices[ticker].dropna()
        observations = len(raw)
        missing_ratio = float(prices[ticker].isna().mean())
        last_date = pd.Timestamp(raw.index.max()).normalize() if observations else pd.NaT
        stale_days = len(pd.bdate_range(last_date, as_of)) - 1 if observations else 9999
        if observations < config.min_observations:
            reason = "insufficient_history"
        elif missing_ratio > config.max_missing_ratio:
            reason = "excessive_missing_data"
        elif stale_days > config.stale_business_days:
            reason = "stale_price"
        elif (raw <= 0).any():
            reason = "non_positive_price"
        if reason == "accepted":
            # Limit=2 prevents long suspensions from becoming fabricated flat prices; no bfill.
            accepted[ticker] = prices[ticker].ffill(limit=2)
        rows.append({"Ticker": ticker, "Status": "accepted" if reason == "accepted" else "rejected", "Reason": reason, "Observations": observations, "Missing_Ratio": missing_ratio, "Last_Date": "" if pd.isna(last_date) else str(last_date.date())})
    return pd.DataFrame(accepted), pd.DataFrame(rows)


def robust_zscore(series: pd.Series, clip: float = 3.0) -> pd.Series:
    """Median/MAD z-score, clipped to keep single outliers from dominating."""
    s = pd.to_numeric(series, errors="coerce")
    median = s.median()
    mad = (s - median).abs().median()
    if not np.isfinite(mad) or mad < 1e-12:
        return pd.Series(0.0, index=s.index)
    return ((s - median) / (1.4826 * mad)).clip(-clip, clip).fillna(0.0)


def _return_at(series: pd.Series, end_offset: int, lookback: int) -> float:
    end = series.iloc[-1 - end_offset]
    start = series.iloc[-1 - end_offset - lookback]
    return float(end / start - 1.0)


def analyze_lumus_engine(prices: pd.DataFrame, region: str, config: ScreeningConfig, sectors: Mapping[str, str] | None = None) -> pd.DataFrame:
    """Calculate robust PURE momentum scores from quality-gated close prices."""
    metrics = {}
    sectors = sectors or {}
    for ticker in prices.columns:
        series = prices[ticker].dropna()
        if len(series) < config.min_observations:
            continue
        returns = series.pct_change(fill_method=None).dropna()
        if len(returns) < 200:
            continue
        r12_1 = _return_at(series, config.skip_recent, 252)
        r6_1 = _return_at(series, config.skip_recent, 126)
        r3_1 = _return_at(series, config.skip_recent, 63)
        momentum = 0.50 * r12_1 + 0.30 * r6_1 + 0.20 * r3_1
        vol = float(returns.tail(252).std(ddof=1) * math.sqrt(252))
        if not np.isfinite(vol) or vol <= 1e-6:
            continue
        positive_ratio = float((returns.tail(252) > 0).mean())
        log_prices = np.log(series.tail(252).to_numpy())
        x = np.arange(len(log_prices))
        corr = np.corrcoef(x, log_prices)[0, 1]
        trend_r2 = float(corr * corr) if np.isfinite(corr) else 0.0
        quality = 0.5 * positive_ratio + 0.5 * trend_r2
        ma200 = float(series.tail(200).mean())
        above_ma200 = bool(series.iloc[-1] > ma200)
        metrics[ticker] = {
            "Region": region, "Sector": sectors.get(ticker, "UNKNOWN"),
            "Momentum_12_1": r12_1, "Momentum_6_1": r6_1, "Momentum_3_1": r3_1,
            "Composite_Momentum": momentum, "Volatility": vol, "Efficiency": momentum / vol,
            "Positive_Day_Ratio": positive_ratio, "Trend_R2": trend_r2, "Quality": quality,
            "Above_MA200": above_ma200, "Last_Price": float(series.iloc[-1]),
        }
    df = pd.DataFrame(metrics).T
    if df.empty:
        return df
    # Eligibility filter makes the 200-day rule meaningful; regime never shifts every score equally.
    df["Eligible"] = df["Above_MA200"] & (df["Composite_Momentum"] > 0)
    df["Total_Score"] = (
        config.score_momentum_weight * robust_zscore(df["Composite_Momentum"])
        + config.score_quality_weight * robust_zscore(df["Quality"])
        + config.score_low_vol_weight * robust_zscore(-df["Volatility"])
    )
    return df.sort_values(["Eligible", "Total_Score"], ascending=[False, False])


def bounded_inverse_volatility(volatility: pd.Series, minimum: float, maximum: float) -> pd.Series:
    """Inverse-volatility weights projected into min/max bounds."""
    if volatility.empty or (volatility <= 0).any() or minimum * len(volatility) > 1 or maximum * len(volatility) < 1:
        raise ValueError("Invalid volatility or infeasible weight bounds")
    raw = (1 / volatility) / (1 / volatility).sum()
    weights = raw.copy()
    for _ in range(100):
        clipped = weights.clip(minimum, maximum)
        fixed = (clipped <= minimum + 1e-12) | (clipped >= maximum - 1e-12)
        remaining = 1 - clipped[fixed].sum()
        if (~fixed).sum() == 0:
            weights = clipped
            break
        base = raw[~fixed]
        weights = clipped
        weights.loc[~fixed] = remaining * base / base.sum()
        if ((weights >= minimum - 1e-10) & (weights <= maximum + 1e-10)).all():
            break
    return weights / weights.sum()


def build_lumus_portfolio(df_us: pd.DataFrame, df_jp: pd.DataFrame, config: ScreeningConfig) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    selected = []
    for region, frame in (("US", df_us), ("JP", df_jp)):
        eligible = frame[frame["Eligible"]].head(config.selected_per_region) if not frame.empty else frame
        if len(eligible) < config.selected_per_region:
            warnings.append(f"{region}: eligible candidates {len(eligible)}/{config.selected_per_region}; portfolio is incomplete")
        selected.append(eligible)
    portfolio = pd.concat(selected) if selected else pd.DataFrame()
    if portfolio.empty:
        return portfolio, warnings + ["No eligible candidates; no portfolio generated"]
    minimum_count = math.ceil(1 / config.max_weight)
    if len(portfolio) < minimum_count:
        warnings.append(f"Only {len(portfolio)} candidates; at least {minimum_count} are required by the max-weight constraint")
        return pd.DataFrame(), warnings
    portfolio = portfolio.copy()
    portfolio["Weight"] = bounded_inverse_volatility(portfolio["Volatility"].astype(float), config.min_weight, config.max_weight)
    portfolio["Weight_Pct"] = portfolio["Weight"] * 100
    known = portfolio[portfolio["Sector"] != "UNKNOWN"]
    if known.empty:
        warnings.append("Sector concentration not measurable: sector metadata is unavailable")
    else:
        for sector, count in known["Sector"].value_counts().items():
            if count >= config.sector_warning_threshold:
                warnings.append(f"Sector concentration: {sector} has {count} selections")
    return portfolio.sort_values("Weight", ascending=False), warnings


def check_regime(index_prices: Mapping[str, pd.Series]) -> dict[str, str]:
    regimes = {}
    for region in ("US", "JP"):
        series = index_prices.get(region, pd.Series(dtype=float)).dropna()
        regimes[region] = "UNKNOWN" if len(series) < 200 else ("BULL" if series.iloc[-1] > series.tail(200).mean() else "BEAR")
    return regimes


def determine_exposure(regimes: Mapping[str, str]) -> float:
    """Advisory PURE exposure only. UNKNOWN is never treated as BULL."""
    states = [regimes.get("US", "UNKNOWN"), regimes.get("JP", "UNKNOWN")]
    if states == ["BULL", "BULL"]:
        return 1.0
    if "UNKNOWN" in states:
        return 0.2 if states.count("UNKNOWN") == 2 else 0.6
    return 0.6 if "BULL" in states else 0.2


def generate_trade_orders(portfolio: pd.DataFrame, budget_jpy: float, usdjpy: float | None) -> pd.DataFrame:
    """Create a REVIEW_REQUIRED order worksheet; refuse USD sizing without FX."""
    rows = []
    for ticker, row in portfolio.iterrows():
        is_jp = str(ticker).endswith(".T")
        if not is_jp and (usdjpy is None or not np.isfinite(usdjpy) or usdjpy <= 0):
            rows.append({"Ticker": ticker, "Status": "BLOCKED_FX_MISSING", "Shares": 0})
            continue
        local_price = float(row["Last_Price"])
        price_jpy = local_price if is_jp else local_price * float(usdjpy)
        lot = 100 if is_jp else 1
        target = budget_jpy * float(row["Weight"])
        shares = int(target // (price_jpy * lot)) * lot
        rows.append({"Ticker": ticker, "Status": "REVIEW_REQUIRED", "Currency": "JPY" if is_jp else "USD", "Price_Local": local_price, "FX_USDJPY": np.nan if is_jp else usdjpy, "Lot_Size": lot, "Shares": shares, "Target_JPY": round(target), "Estimated_Cost_JPY": round(shares * price_jpy), "Limit_Price": ""})
    orders = pd.DataFrame(rows)
    if not orders.empty:
        total = orders.get("Estimated_Cost_JPY", pd.Series(dtype=float)).fillna(0).sum()
        orders.attrs["cash_remainder_jpy"] = budget_jpy - total
    return orders


def make_demo_prices(tickers: Sequence[str], seed: int, periods: int = 320) -> pd.DataFrame:
    """Deterministic offline data for smoke tests and demonstrations."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-06-05", periods=periods)
    result = {}
    for i, ticker in enumerate(tickers):
        drift = 0.00025 + (i % 10) * 0.00008
        vol = 0.009 + (i % 5) * 0.0015
        returns = rng.normal(drift, vol, periods)
        result[ticker] = 100 * np.exp(np.cumsum(returns))
    return pd.DataFrame(result, index=dates)


def load_sector_map(path: Path | None) -> dict[str, str]:
    """Load optional Ticker,Sector metadata used for concentration warnings."""
    if path is None:
        return {}
    frame = pd.read_csv(path)
    required = {"Ticker", "Sector"}
    if not required.issubset(frame.columns):
        raise ValueError(f"sector map must contain {sorted(required)}")
    return {str(row.Ticker): str(row.Sector) for row in frame.itertuples()}


def run(output_dir: Path, demo: bool, config: ScreeningConfig, sector_map: Path | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    if demo:
        us = [f"US{i:02d}" for i in range(20)]
        jp = [f"{1000+i}.T" for i in range(20)]
        prices_us, prices_jp = make_demo_prices(us, 8), make_demo_prices(jp, 108)
        sectors = {t: ["Technology", "Industrials", "Financials", "Consumer"][i % 4] for i, t in enumerate(us + jp)}
        index_prices = {"US": prices_us.mean(axis=1), "JP": prices_jp.mean(axis=1)}
        usdjpy = 155.0
    else:
        us, jp = get_tickers_lumus()
        prices_us = download_close(us, config.history_days)
        prices_jp = download_close(jp, config.history_days)
        sectors = load_sector_map(sector_map)
        idx = download_close(["^GSPC", "^N225"], config.history_days)
        index_prices = {"US": idx.get("^GSPC", pd.Series(dtype=float)), "JP": idx.get("^N225", pd.Series(dtype=float))}
        fx = download_close(["JPY=X"], 10)
        usdjpy = float(fx["JPY=X"].dropna().iloc[-1]) if "JPY=X" in fx and not fx["JPY=X"].dropna().empty else None
    accepted_us, report_us = data_quality_gate(prices_us, us, config)
    accepted_jp, report_jp = data_quality_gate(prices_jp, jp, config)
    scores_us = analyze_lumus_engine(accepted_us, "US", config, sectors)
    scores_jp = analyze_lumus_engine(accepted_jp, "JP", config, sectors)
    portfolio, warnings = build_lumus_portfolio(scores_us, scores_jp, config)
    regimes = check_regime(index_prices)
    exposure = determine_exposure(regimes)
    budget = config.total_budget_jpy * exposure
    orders = generate_trade_orders(portfolio, budget, usdjpy)
    quality = pd.concat([report_us.assign(Region="US"), report_jp.assign(Region="JP")], ignore_index=True)
    quality.to_csv(output_dir / "quality_report.csv", index=False)
    pd.concat([scores_us, scores_jp]).to_csv(output_dir / "all_scores.csv", index_label="Ticker")
    portfolio.to_csv(output_dir / "selected_portfolio.csv", index_label="Ticker")
    orders.to_csv(output_dir / "review_required_orders.csv", index=False)
    rejected = quality[quality["Status"] == "rejected"]
    manifest = {"as_of": str(date.today()), "mode": "demo" if demo else "live", "config": asdict(config), "regimes": regimes, "unknown_regime_policy": "UNKNOWN never maps to BULL", "advisory_exposure": exposure, "fx_usdjpy": usdjpy, "quality_summary": {"accepted": int((quality["Status"] == "accepted").sum()), "rejected": len(rejected), "rejection_reasons": rejected["Reason"].value_counts().to_dict()}, "selection_summary": portfolio["Region"].value_counts().to_dict() if not portfolio.empty else {}, "order_policy": "All rows require human review; US rows stop when FX is missing", "order_status_summary": orders["Status"].value_counts().to_dict() if not orders.empty else {}, "warnings": warnings, "cash_remainder_jpy": orders.attrs.get("cash_remainder_jpy")}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    LOGGER.info("Selected %d candidates; outputs written to %s", len(portfolio), output_dir)
    for warning in warnings:
        LOGGER.warning(warning)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="L.U.M.U.S.-8 momentum screening PURE Edition")
    parser.add_argument("--demo", action="store_true", help="run deterministic offline demonstration")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--sector-map", type=Path, help="optional CSV with Ticker,Sector columns")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    if args.demo:
        from portable_demo import run_portable_demo
        manifest = run_portable_demo(args.output_dir, ScreeningConfig())
    else:
        global np, pd, requests, yf
        import importlib
        np = importlib.import_module("numpy")
        pd = importlib.import_module("pandas")
        requests = importlib.import_module("requests")
        yf = importlib.import_module("yfinance")
        manifest = run(args.output_dir, False, ScreeningConfig(), args.sector_map)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
