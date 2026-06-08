import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

from momentum_screening_pure import (
    ScreeningConfig, analyze_lumus_engine, bounded_inverse_volatility,
    build_lumus_portfolio, data_quality_gate, generate_trade_orders,
    make_demo_prices, normalize_ticker, robust_zscore,
)


def test_ticker_normalization_preserves_japan_and_fixes_us_class_shares():
    assert normalize_ticker("BRK.B", "US") == "BRK-B"
    assert normalize_ticker("bf.b", "US") == "BF-B"
    assert normalize_ticker("7203.T", "JP") == "7203.T"
    assert normalize_ticker("7203", "JP") == "7203.T"


def test_quality_gate_rejects_missing_and_does_not_backfill_leading_gap():
    cfg = ScreeningConfig(min_observations=274, max_missing_ratio=0.03)
    prices = make_demo_prices(["GOOD", "SHORT"], 1)
    prices.loc[prices.index[:10], "GOOD"] = np.nan
    prices.loc[prices.index[:60], "SHORT"] = np.nan
    accepted, report = data_quality_gate(prices, ["GOOD", "SHORT", "ABSENT"], cfg)
    assert "GOOD" not in accepted  # 10 / 320 exceeds the configured quality threshold
    assert set(report.loc[report.Status == "rejected", "Ticker"]) == {"GOOD", "SHORT", "ABSENT"}


def test_score_is_finite_and_outlier_is_clipped():
    z = robust_zscore(pd.Series([1, 2, 3, 4, 1_000]))
    assert z.max() == 3.0
    prices = make_demo_prices([f"T{i}" for i in range(10)], 2)
    scores = analyze_lumus_engine(prices, "US", ScreeningConfig())
    assert np.isfinite(scores["Total_Score"].astype(float)).all()
    assert (scores["Total_Score"].abs() <= 3).all()


def test_bounded_inverse_volatility_obeys_constraints():
    weights = bounded_inverse_volatility(pd.Series([0.1, 0.2, 0.3, 0.8] * 3), 0.04, 0.12)
    assert weights.sum() == pytest.approx(1.0)
    assert weights.min() >= 0.04 - 1e-10
    assert weights.max() <= 0.12 + 1e-10


def test_portfolio_and_orders_are_review_only_and_use_jp_board_lots():
    cfg = ScreeningConfig()
    us_prices = make_demo_prices([f"US{i}" for i in range(12)], 3)
    jp_prices = make_demo_prices([f"{1000+i}.T" for i in range(12)], 4)
    us = analyze_lumus_engine(us_prices, "US", cfg)
    jp = analyze_lumus_engine(jp_prices, "JP", cfg)
    portfolio, _ = build_lumus_portfolio(us, jp, cfg)
    orders = generate_trade_orders(portfolio, 4_500_000, 150.0)
    assert set(orders.Status) == {"REVIEW_REQUIRED"}
    assert (orders.loc[orders.Ticker.str.endswith(".T"), "Shares"] % 100 == 0).all()
    assert orders.attrs["cash_remainder_jpy"] >= 0


def test_missing_fx_blocks_us_orders():
    portfolio = pd.DataFrame({"Last_Price": [100.0], "Weight": [1.0]}, index=["MSFT"])
    orders = generate_trade_orders(portfolio, 100_000, None)
    assert orders.iloc[0].Status == "BLOCKED_FX_MISSING"
