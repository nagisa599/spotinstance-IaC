#!/usr/bin/env python3
"""
Phase 1: 既存の観測データ (data/*.csv) のみを用いた戦略シミュレーション.

main.tex の定義に合わせる:
  - F_comp(d) = 1 - R_int(d)  : 期限 d まで中断されなかった起動成功インスタンスの割合
  - 時間帯は launch_time をリージョンのローカル時刻に直して 4 分割
  - F_comp は起動成功インスタンス (N_succ) のみで定義

ここで計算するもの:
  p       = F_comp(d)                        (リージョン x タイプ x 時間帯 x d)
  u_bar   = E[U | U < d]                     中断された試行の平均稼働時間
  P_spot  = 観測されたスポット価格の平均      (リージョン x タイプ)

戦略 S0..S4 を、到着時刻 t0 を 24 時間に振って比較する.
"""
import glob
import itertools
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

DATA_DIR = "data"
DEADLINES = [5, 10, 30, 60]          # d (分)
SLACKS_H = [0, 1, 3, 6, 12]          # D_j - d_j (時間)
P_MINS = [0.0, 0.8, 0.9]
DATE_START = "2026-05-19T00:00:00Z"
DATE_END = "2026-05-26T00:00:00Z"

REGION_TZ = {
    "ap-northeast-1": ZoneInfo("Asia/Tokyo"),
    "ap-southeast-1": ZoneInfo("Asia/Singapore"),
    "eu-west-1":      ZoneInfo("Europe/Dublin"),
    "us-east-1":      ZoneInfo("America/New_York"),
}
REGION_LABELS = {
    "ap-northeast-1": "Tokyo",
    "ap-southeast-1": "Singapore",
    "eu-west-1":      "Ireland",
    "us-east-1":      "N.Virginia",
}
REGIONS = list(REGION_TZ)
TYPES = ["c6a.large", "g4dn.xlarge", "t3.micro"]
PERIODS = ["Night", "Morning", "Afternoon", "Evening"]

STARTUP_S = 4.5   # 実測 (startup_s の平均)
Z = 1.96          # 95% CI


def classify_period(h: int) -> str:
    if h < 6:
        return "Night"
    if h < 12:
        return "Morning"
    if h < 18:
        return "Afternoon"
    return "Evening"


# ── データ読み込み (figure.py と同じ前処理) ──────────────────────────────────
def load() -> pd.DataFrame:
    df = pd.concat([pd.read_csv(f) for f in glob.glob(f"{DATA_DIR}/*.csv")],
                   ignore_index=True)
    df = df.drop_duplicates(subset="run_id").reset_index(drop=True)
    df = df[(df["timestamp"] >= DATE_START) & (df["timestamp"] < DATE_END)]
    df = df[~df["launch_failed"].astype(bool)].reset_index(drop=True)

    dt = pd.to_datetime(df["launch_time"], utc=True)
    df["local_hour"] = [d.astimezone(REGION_TZ[r]).hour
                        for d, r in zip(dt, df["region"])]
    df["period"] = df["local_hour"].apply(classify_period)
    df["interrupted"] = df["interrupted"].astype(bool)
    return df


def wilson_lcb(k: int, n: int) -> float:
    """Wilson の下側信頼限界 (95%)."""
    if n == 0:
        return 0.0
    ph = k / n
    denom = 1 + Z**2 / n
    centre = ph + Z**2 / (2 * n)
    margin = Z * np.sqrt(ph * (1 - ph) / n + Z**2 / (4 * n**2))
    return max(0.0, (centre - margin) / denom)


# ── 3 つのテーブルを作る ────────────────────────────────────────────────────
def build_tables(df: pd.DataFrame):
    """p[(r,tau,period,d)], p_lcb[...], u_bar[(r,tau,period,d)], price[(r,tau)]"""
    p, p_lcb, u_bar, n_tab = {}, {}, {}, {}

    for (r, tau, per), g in df.groupby(["region", "instance_type", "period"]):
        n = len(g)
        for d in DEADLINES:
            d_sec = d * 60
            # main.tex の F_comp: 中断されなかった or d 分以上生存したら「完了」
            completed = (~g["interrupted"]) | (g["uptime_s"] >= d_sec)
            k = int(completed.sum())
            p[(r, tau, per, d)] = k / n
            p_lcb[(r, tau, per, d)] = wilson_lcb(k, n)
            n_tab[(r, tau, per, d)] = n

            # u_bar = E[U | U < d] : d 分より前に中断された試行の平均稼働時間
            failed = g[g["interrupted"] & (g["uptime_s"] < d_sec)]
            u_bar[(r, tau, per, d)] = (failed["uptime_s"].mean() / 60
                                       if len(failed) else 0.0)

    price = df.groupby(["region", "instance_type"])["spot_price"].mean().to_dict()
    return p, p_lcb, u_bar, n_tab, price


# ── コストモデル (future-main.tex の式) ──────────────────────────────────────
def billed_minutes(p_val: float, u: float, d: int) -> float:
    """E[課金時間] = d + (1/p - 1) * u_bar"""
    if p_val <= 0:
        return float("inf")
    return d + (1.0 / p_val - 1.0) * u


def cost_usd(price_h: float, p_val: float, u: float, d: int) -> float:
    return price_h / 60.0 * billed_minutes(p_val, u, d)


def expected_finish_min(p_val: float, d: int, wait_h: float) -> float:
    """E[T_finish] ~ 待ち時間 + (1/p)(s + d)"""
    if p_val <= 0:
        return float("inf")
    return wait_h * 60.0 + (1.0 / p_val) * (STARTUP_S / 60.0 + d)


def period_at(r: str, t0_utc_hour: int, shift_h: int) -> str:
    """UTC 時刻 t0 + shift のリージョン r におけるローカル時間帯."""
    base = pd.Timestamp("2026-05-20T00:00:00Z") + pd.Timedelta(hours=t0_utc_hour + shift_h)
    return classify_period(base.astimezone(REGION_TZ[r]).hour)


# ── 戦略 ────────────────────────────────────────────────────────────────────
def solve(strategy, t0, d, slack_h, p_min, tables,
          R_allowed=None, T_allowed=None, default_region="us-east-1",
          default_type="c6a.large"):
    """式(opt)を全探索で解く。戦略ごとに探索範囲と目的関数を変える。"""
    p, p_lcb, u_bar, n_tab, price = tables
    R_allowed = R_allowed or REGIONS
    T_allowed = T_allowed or TYPES

    # 戦略ごとの探索範囲
    if strategy == "S0":                       # 固定・即時
        cand_r, cand_tau, cand_shift = [default_region], [default_type], [0]
    elif strategy == "S1":                     # 最安値・即時
        cheapest = min(((r, t) for r in R_allowed for t in T_allowed),
                       key=lambda x: price[x])
        cand_r, cand_tau, cand_shift = [cheapest[0]], [cheapest[1]], [0]
    elif strategy == "S2":                     # リージョン/タイプ自由・即時
        cand_r, cand_tau, cand_shift = R_allowed, T_allowed, [0]
    else:                                      # S3 / S3-LCB / S4: すべて自由
        max_shift = max(0, int(slack_h))
        cand_r, cand_tau, cand_shift = R_allowed, T_allowed, range(max_shift + 1)

    use_lcb = (strategy == "S3-LCB")
    p_tab = p_lcb if use_lcb else p

    best, best_key = None, float("inf")
    for r, tau, sh in itertools.product(cand_r, cand_tau, cand_shift):
        per = period_at(r, t0, sh)
        key = (r, tau, per, d)
        pv_sel = p_tab[key]        # 選択に使う確率
        pv_true = p[key]           # 評価に使う確率 (実測の点推定)
        uv = u_bar[key]

        # 制約: 信頼性下限
        if pv_sel < p_min:
            continue
        # 制約: 締切 (D_j = d + slack)
        if expected_finish_min(pv_sel, d, sh) > d + slack_h * 60:
            continue

        c_sel = cost_usd(price[(r, tau)], pv_sel, uv, d)
        # S1 は価格のみで選ぶ (p を無視)
        rank = price[(r, tau)] if strategy == "S1" else c_sel

        if rank < best_key:
            best_key = rank
            best = dict(region=r, itype=tau, shift_h=sh, period=per,
                        p=pv_true, u_bar=uv,
                        cost=cost_usd(price[(r, tau)], pv_true, uv, d),
                        billed=billed_minutes(pv_true, uv, d))
    return best


def oracle(t0, d, slack_h, tables):
    """S4: 実測の p で直接最良を選ぶ (達成可能な上界)."""
    return solve("S4", t0, d, slack_h, 0.0, tables)


# ── 実験 ────────────────────────────────────────────────────────────────────
def main():
    df = load()
    tables = build_tables(df)
    p, p_lcb, u_bar, n_tab, price = tables

    print("=" * 78)
    print("観測データの要約")
    print("=" * 78)
    print(f"起動成功インスタンス数 N_succ = {len(df)}")
    print(f"中断された数              = {int(df['interrupted'].sum())} "
          f"({df['interrupted'].mean()*100:.1f}%)")
    print()

    print("--- p = F_comp(60) [実測] ---")
    rows = []
    for r in REGIONS:
        for tau in TYPES:
            rows.append({
                "region": REGION_LABELS[r], "type": tau,
                **{per: round(p[(r, tau, per, 60)], 3) for per in PERIODS},
                "price": round(price[(r, tau)], 4),
            })
    print(pd.DataFrame(rows).to_string(index=False))
    print()

    print("--- u_bar = E[U|U<60] (分) : 中断された試行の平均稼働時間 ---")
    rows = []
    for r in REGIONS:
        for tau in TYPES:
            rows.append({
                "region": REGION_LABELS[r], "type": tau,
                **{per: round(u_bar[(r, tau, per, 60)], 1) for per in PERIODS},
            })
    print(pd.DataFrame(rows).to_string(index=False))
    print()

    # ── 戦略比較: 到着時刻 t0 を 24 時間に振って平均 ──────────────────────
    # タイプを固定して比較する (T_FIX)。タイプ自由だと価格差が支配して
    # 信頼性の効果が見えなくなるため (d(tau) 交絡)。
    strategies = ["S0", "S1", "S2", "S3", "S3-LCB", "S4"]
    results = []
    for T_FIX, d, slack_h, p_min, st in itertools.product(
            TYPES, DEADLINES, SLACKS_H, P_MINS, strategies):
        costs, billeds, ps, feasible = [], [], [], 0
        choices = []
        for t0 in range(24):
            sol = solve(st, t0, d, slack_h, p_min, tables,
                        T_allowed=[T_FIX], default_type=T_FIX)
            if sol is None:
                continue
            feasible += 1
            costs.append(sol["cost"])
            billeds.append(sol["billed"])
            ps.append(sol["p"])
            choices.append((REGION_LABELS[sol["region"]], sol["itype"],
                            sol["period"], sol["shift_h"]))
        if not costs:
            continue
        results.append(dict(itype=T_FIX, d=d, slack_h=slack_h, p_min=p_min,
                            strategy=st,
                            cost=np.mean(costs), billed=np.mean(billeds),
                            p=np.mean(ps), feasible=feasible / 24,
                            choices=choices))

    res = pd.DataFrame(results)
    res.to_csv("phase1_results.csv", index=False)

    # ── 主要な比較表 (p_min=0, タイプ固定) ──────────────────────────────
    print("=" * 78)
    print("戦略比較: 平均期待コスト (USD), t0 を 24 時間で平均, p_min=0")
    print("  ※ インスタンスタイプは固定。自由にすると価格差(t3.micro が 7 倍安い)")
    print("     が支配し、信頼性の効果が見えなくなるため。")
    print("=" * 78)
    for T_FIX in TYPES:
        for d in [60]:
            print(f"\n### {T_FIX}, d = {d} 分")
            sub = res[(res["itype"] == T_FIX) & (res["d"] == d) &
                      (res["p_min"] == 0.0)]
            piv = sub.pivot(index="strategy", columns="slack_h",
                            values="cost").reindex(strategies)
            base = piv.loc["S0"]
            out = piv.copy()
            for c in out.columns:
                out[c] = [f"{v:.5f} ({(v/base[c]-1)*100:+.1f}%)" for v in piv[c]]
            out.columns = [f"slack={c}h" for c in out.columns]
            print(out.to_string())

    # ── 無駄時間 (価格を除いた信頼性の効果) ──────────────────────────────
    print()
    print("=" * 78)
    print("やり直しによる無駄時間 (分) = E[課金時間] - d   [c6a.large, d=60]")
    print("  価格の影響を除き、信頼性の効果だけを見る")
    print("=" * 78)
    sub = res[(res["itype"] == "c6a.large") & (res["d"] == 60) &
              (res["p_min"] == 0.0)]
    piv = sub.pivot(index="strategy", columns="slack_h",
                    values="billed").reindex(strategies) - 60
    base = piv.loc["S0"]
    out = piv.copy()
    for c in out.columns:
        out[c] = [f"{v:.2f}分 ({(v/base[c]-1)*100:+.0f}%)" for v in piv[c]]
    out.columns = [f"slack={c}h" for c in out.columns]
    print(out.to_string())

    # ── 平均成功確率 p ──────────────────────────────────────────────────
    print()
    print("=" * 78)
    print("戦略が選んだ条件の平均成功確率 p  (c6a.large, d=60, p_min=0)")
    print("=" * 78)
    sub = res[(res["itype"] == "c6a.large") & (res["d"] == 60) &
              (res["p_min"] == 0.0)]
    piv = sub.pivot(index="strategy", columns="slack_h",
                    values="p").reindex(strategies)
    piv.columns = [f"slack={c}h" for c in piv.columns]
    print(piv.round(4).to_string())

    # ── 選択されたリージョン/時間帯の分布 ────────────────────────────────
    print()
    print("=" * 78)
    print("S3 が選んだ条件の分布 (c6a.large, d=60, slack=6h, p_min=0)")
    print("=" * 78)
    row = res[(res["itype"] == "c6a.large") & (res["d"] == 60) &
              (res["slack_h"] == 6) & (res["p_min"] == 0.0) &
              (res["strategy"] == "S3")]
    ch = pd.DataFrame(row.iloc[0]["choices"],
                      columns=["region", "type", "period", "shift_h"])
    for col in ["region", "period", "shift_h"]:
        vc = ch[col].value_counts()
        print(f"\n{col}:")
        print((vc / len(ch) * 100).round(1).to_string())

    # ── S0 が当たる最悪条件 ──────────────────────────────────────────────
    print()
    print("=" * 78)
    print("参考: S0 (us-east-1 / c6a.large 固定・即時) が時間帯ごとに当たる p")
    print("=" * 78)
    for per in PERIODS:
        print(f"  {per:10s}: p={p[('us-east-1','c6a.large',per,60)]:.3f}  "
              f"u_bar={u_bar[('us-east-1','c6a.large',per,60)]:.1f}分  "
              f"n={n_tab[('us-east-1','c6a.large',per,60)]}")

    # ── winner's curse: S3 と S3-LCB の選択差 ──────────────────────────
    print()
    print("=" * 78)
    print("winner's curse: S3 と S3-LCB が違う条件を選んだ割合")
    print("=" * 78)
    for d in DEADLINES:
        diff = 0
        for t0 in range(24):
            a = solve("S3", t0, d, 6, 0.0, tables, T_allowed=["c6a.large"], default_type="c6a.large")
            b = solve("S3-LCB", t0, d, 6, 0.0, tables, T_allowed=["c6a.large"], default_type="c6a.large")
            if a and b and (a["region"], a["itype"], a["shift_h"]) != \
                           (b["region"], b["itype"], b["shift_h"]):
                diff += 1
        print(f"  d={d:2d}分: {diff}/24 時刻で選択が変わった ({diff/24*100:.0f}%)")

    print()
    print("保存: phase1_results.csv")


if __name__ == "__main__":
    main()
