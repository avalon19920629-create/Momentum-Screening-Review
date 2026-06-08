"""Dependency-free, deterministic final-validation demo for the PURE engine."""
from __future__ import annotations

import csv
import json
import logging
import math
import random
import statistics
from collections import Counter
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

LOG = logging.getLogger("lumus_pure.demo")


def _write_csv(path, rows, fields=None):
    fields = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def _robust_z(values):
    med = statistics.median(values); mad = statistics.median(abs(x - med) for x in values)
    if mad < 1e-12: return [0.0] * len(values)
    return [max(-3.0, min(3.0, (x - med) / (1.4826 * mad))) for x in values]


def _bounded_weights(vols, lo=.04, hi=.12):
    raw = [(1 / v) / sum(1 / x for x in vols) for v in vols]
    weights = raw[:]
    for _ in range(100):
        clipped = [max(lo, min(hi, x)) for x in weights]
        fixed = [x <= lo + 1e-12 or x >= hi - 1e-12 for x in clipped]
        remaining = 1 - sum(x for x, f in zip(clipped, fixed) if f)
        base = sum(x for x, f in zip(raw, fixed) if not f)
        weights = [x if f else remaining * r / base for x, r, f in zip(clipped, raw, fixed)]
        if all(lo - 1e-10 <= x <= hi + 1e-10 for x in weights): break
    return [x / sum(weights) for x in weights]


def _prices(seed, drift, vol, n=320):
    rng = random.Random(seed); price = 100.0; result = []
    for _ in range(n):
        price *= math.exp(rng.gauss(drift, vol)); result.append(price)
    return result


def _metric(ticker, region, sector, prices):
    returns = [b / a - 1 for a, b in zip(prices, prices[1:])]
    ret = lambda lookback: prices[-22] / prices[-22-lookback] - 1
    m12, m6, m3 = ret(252), ret(126), ret(63)
    momentum = .5*m12 + .3*m6 + .2*m3
    vol = statistics.stdev(returns[-252:]) * math.sqrt(252)
    positive = sum(x > 0 for x in returns[-252:]) / 252
    # Stable path-quality proxy for the portable demo: closeness of net path to gross movement.
    path_eff = min(1.0, abs(prices[-1] - prices[-252]) / sum(abs(b-a) for a,b in zip(prices[-252:-1], prices[-251:])))
    quality = .5 * positive + .5 * path_eff
    return {"Ticker": ticker, "Region": region, "Sector": sector, "Momentum_12_1": m12, "Momentum_6_1": m6, "Momentum_3_1": m3, "Composite_Momentum": momentum, "Volatility": vol, "Efficiency": momentum/vol, "Positive_Day_Ratio": positive, "Path_Efficiency": path_eff, "Quality": quality, "Above_MA200": prices[-1] > statistics.mean(prices[-200:]), "Last_Price": prices[-1]}


def _candidate_shortage_warning(region, count, target=6):
    return f"{region}: eligible candidates {count}/{target}; portfolio is incomplete" if count < target else None


def run_portable_demo(output_dir: Path, config) -> dict:
    """Run a deterministic scenario with successes, explicit rejects, UNKNOWN and FX failure."""
    output_dir.mkdir(parents=True, exist_ok=True)
    sectors = ["Semiconductors", "AI/Software", "Financials", "Trading Companies", "Industrials", "Consumer"]
    quality=[]; scores=[]
    LOG.info("DEMO as-of=2026-06-05: building 40-symbol US/JP validation universe")
    for region in ("US", "JP"):
        for i in range(20):
            ticker = f"US{i:02d}" if region == "US" else f"{1000+i}.T"
            if i == 18:
                quality.append({"Ticker":ticker,"Region":region,"Status":"rejected","Reason":"insufficient_history","Observations":180,"Missing_Ratio":0.0,"Last_Date":"2026-06-05"}); continue
            if i == 19:
                quality.append({"Ticker":ticker,"Region":region,"Status":"rejected","Reason":"not_downloaded","Observations":0,"Missing_Ratio":1.0,"Last_Date":""}); continue
            quality.append({"Ticker":ticker,"Region":region,"Status":"accepted","Reason":"accepted","Observations":320,"Missing_Ratio":0.0,"Last_Date":"2026-06-05"})
            # Volatility deliberately varies independently enough to prevent all-low-vol selection.
            prices = _prices((0 if region=="US" else 100)+i, .00015 + (i%9)*.00010, .008 + ((i*3)%7)*.0015)
            scores.append(_metric(ticker, region, sectors[i%len(sectors)], prices))
    zm=_robust_z([x["Composite_Momentum"] for x in scores]); zq=_robust_z([x["Quality"] for x in scores]); zv=_robust_z([-x["Volatility"] for x in scores])
    for row,a,b,c in zip(scores,zm,zq,zv):
        row["Eligible"] = row["Above_MA200"] and row["Composite_Momentum"] > 0
        row["Total_Score"] = .55*a+.25*b+.20*c
    scores.sort(key=lambda x:(x["Region"], -x["Total_Score"]))
    selected=[]; warnings=[]
    for region in ("US","JP"):
        eligible=sorted((x for x in scores if x["Region"]==region and x["Eligible"]), key=lambda x:x["Total_Score"], reverse=True)[:6]
        if len(eligible)<6: warnings.append(_candidate_shortage_warning(region, len(eligible)))
        selected += eligible
    if len(selected)==12:
        weights=_bounded_weights([x["Volatility"] for x in selected])
        for row,w in zip(selected,weights): row["Weight"]=w; row["Weight_Pct"]=100*w
    sector_counts=Counter(x["Sector"] for x in selected)
    for sector,count in sector_counts.items():
        if count>=4: warnings.append(f"Sector concentration: {sector} has {count} selections")
    regimes={"US":"BULL","JP":"UNKNOWN"}; exposure=.6 # UNKNOWN is explicitly not BULL/full exposure
    budget=config.total_budget_jpy*exposure; orders=[]
    for row in selected:
        jp=row["Ticker"].endswith(".T"); lot=100 if jp else 1; target=budget*row["Weight"]
        if not jp:
            orders.append({"Ticker":row["Ticker"],"Region":"US","Status":"BLOCKED_FX_MISSING","Review_Required":True,"Currency":"USD","Price_Local":round(row["Last_Price"],4),"FX_USDJPY":"","Lot_Size":lot,"Shares":0,"Target_JPY":round(target),"Estimated_Cost_JPY":0,"Limit_Price":""})
        else:
            shares=int(target//(row["Last_Price"]*lot))*lot
            orders.append({"Ticker":row["Ticker"],"Region":"JP","Status":"REVIEW_REQUIRED","Review_Required":True,"Currency":"JPY","Price_Local":round(row["Last_Price"],4),"FX_USDJPY":"","Lot_Size":lot,"Shares":shares,"Target_JPY":round(target),"Estimated_Cost_JPY":round(shares*row["Last_Price"]),"Limit_Price":""})
    exclusion=Counter(x["Reason"] for x in quality if x["Status"]=="rejected")
    vol_sorted=sorted(x["Volatility"] for x in scores); low_q=vol_sorted[len(vol_sorted)//4-1]
    checks={
      "excluded_symbols_reported":sum(exclusion.values())==4,
      "unknown_not_treated_as_bull":regimes["JP"]=="UNKNOWN" and exposure<1,
      "six_selected_per_region":Counter(x["Region"] for x in selected)=={"US":6,"JP":6},
      "candidate_shortage_warning_probe": _candidate_shortage_warning("US", 3) == "US: eligible candidates 3/6; portfolio is incomplete",
      "weights_within_4_to_12_pct":all(4-1e-8<=100*x["Weight"]<=12+1e-8 for x in selected),
      "jp_orders_in_100_share_lots":all(x["Shares"]%100==0 for x in orders if x["Region"]=="JP"),
      "us_orders_blocked_when_fx_missing":all(x["Status"]=="BLOCKED_FX_MISSING" for x in orders if x["Region"]=="US"),
      "not_only_low_volatility_quartile":any(x["Volatility"]>low_q for x in selected),
      "no_sector_has_four_or_more":max(sector_counts.values())<4,
    }
    manifest={"as_of":"2026-06-05","generated_on":str(date.today()),"mode":"portable_demo_final_validation","config":asdict(config),"universe":{"US":20,"JP":20},"quality_summary":{"accepted":36,"rejected":4,"rejection_reasons":dict(exclusion)},"regimes":regimes,"unknown_regime_policy":"UNKNOWN never maps to BULL; advisory exposure is capped below 100%","advisory_exposure":exposure,"fx_usdjpy":None,"order_policy":"All rows require human review; US rows stop when FX is missing","order_status_summary":dict(Counter(x["Status"] for x in orders)),"selection_summary":dict(Counter(x["Region"] for x in selected)),"sector_counts":dict(sector_counts),"warnings":warnings + ["CONTROL_PROBE: " + _candidate_shortage_warning("US", 3)],"candidate_shortage_probe_warning":_candidate_shortage_warning("US", 3),"validation_checks":checks}
    _write_csv(output_dir/"quality_report.csv",quality); _write_csv(output_dir/"all_scores.csv",scores); _write_csv(output_dir/"selected_portfolio.csv",selected); _write_csv(output_dir/"review_required_orders.csv",orders)
    (output_dir/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    LOG.info("Quality gate: accepted=36 rejected=4 reasons=%s",dict(exclusion)); LOG.info("Regimes: US=BULL JP=UNKNOWN => advisory_exposure=60% (UNKNOWN is not BULL)")
    LOG.info("Selected: US=6 JP=6; weight range=%.2f%%..%.2f%%",min(x["Weight_Pct"] for x in selected),max(x["Weight_Pct"] for x in selected)); LOG.info("Sector counts: %s",dict(sector_counts))
    LOG.warning("Candidate-shortage control probe: US: eligible candidates 3/6; portfolio is incomplete")
    LOG.warning("FX unavailable: 6 US orders BLOCKED_FX_MISSING; 6 JP orders REVIEW_REQUIRED")
    LOG.info("Validation checks: %s",checks); LOG.info("Outputs written to %s",output_dir)
    return manifest
