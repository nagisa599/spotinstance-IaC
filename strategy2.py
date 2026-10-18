#!/usr/bin/env python3
"""
実行条件選択モデル (k=1) の評価.

目的関数は「無駄時間」(分)。コストではなく中断による損失そのものを最小化する。
  Waste(r, tau, t) = (1/p - 1) * u_bar + s

決定変数: リージョン r, インスタンスタイプ tau, 起動時刻 t
制約: 締切 (slack), 信頼性下限 p_min, 利用可能な r/tau

戦略:
  B0 Naive       : 固定条件・即時
  B1 Time        : 時刻のみ選択
  B2 Region      : リージョン/タイプのみ選択(即時)
  B3 Proposed    : すべて選択
  B3-LCB         : Wilson 下側信頼限界で保守的に選択
  B4 Oracle      : 実測の点推定で最良(上界)
"""
import glob
import itertools
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

DATA_DIR = "data"
DATE_START = "2026-05-19T00:00:00Z"
DATE_END = "2026-05-26T00:00:00Z"
Z = 1.96

REGION_TZ = {
    "ap-northeast-1": ZoneInfo("Asia/Tokyo"),
    "ap-southeast-1": ZoneInfo("Asia/Singapore"),
    "eu-west-1":      ZoneInfo("Europe/Dublin"),
    "us-east-1":      ZoneInfo("America/New_York"),
}
REGION_LABELS = {
    "ap-northeast-1": "Tokyo", "ap-southeast-1": "Singapore",
    "eu-west-1": "Ireland", "us-east-1": "N.Virginia",
}
REGIONS = list(REGION_TZ)
TYPES = ["c6a.large", "g4dn.xlarge", "t3.micro"]
PERIODS = ["Night", "Morning", "Afternoon", "Evening"]

DEFAULT_REGION = "us-east-1"   # B0 の固定先 (最安リージョン = 不利にしない)


def classify_period(h):
    return ("Night" if h < 6 else "Morning" if h < 12
            else "Afternoon" if h < 18 else "Evening")


def load():
    df = pd.concat([pd.read_csv(f) for f in glob.glob(f"{DATA_DIR}/*.csv")],
                   ignore_index=True).drop_duplicates(subset="run_id")
    df = df[(df["timestamp"] >= DATE_START) & (df["timestamp"] < DATE_END)]
    df = df.reset_index(drop=True)
    df["lf"] = df["launch_failed"].astype(bool)
    ok = df[~df["lf"]].copy()
    dt = pd.to_datetime(ok["launch_time"], utc=True)
    ok["period"] = [classify_period(d.astimezone(REGION_TZ[r]).hour)
                    for d, r in zip(dt, ok["region"])]
    ok["int"] = ok["interrupted"].astype(bool)
    ok["u"] = ok["uptime_s"].astype(float) / 60.0
    s = ok["startup_s"].astype(float).mean() / 60.0
    return df, ok, s


def wilson_lcb(k, n):
    if n == 0:
        return 0.0
    ph = k / n
    return max(0.0, (ph + Z**2/(2*n)
                     - Z*np.sqrt(ph*(1-ph)/n + Z**2/(4*n**2))) / (1 + Z**2/n))


def build_tables(ok, d):
    """p[(r,tau,period)], p_lcb[...], u_bar[...], n[...] を期限 d について作る.

    u_bar は「期限前に中断された試行」の平均稼働時間だが、
    セル内に該当例が 0 件だと u_bar=0 となり、無駄時間が s に潰れてしまう。
    これは標本が少ないことによる見かけの現象であり、
    そのセルを無条件に最良と判定させてしまう。
    そこで該当例が少ないセルでは、全体をプールした値で代用する。
    """
    MIN_FAIL = 3          # これ未満ならプール値を使う
    gf = ok[ok["int"] & (ok["u"] < d)]
    ub_pool = gf["u"].mean() if len(gf) else d / 2.0

    p, p_lcb, ub, nn = {}, {}, {}, {}
    for (r, tau, per), g in ok.groupby(["region", "instance_type", "period"]):
        n = len(g)
        done = (~g["int"]) | (g["u"] >= d)
        k = int(done.sum())
        p[(r, tau, per)] = k / n
        p_lcb[(r, tau, per)] = wilson_lcb(k, n)
        f = g[g["int"] & (g["u"] < d)]
        ub[(r, tau, per)] = f["u"].mean() if len(f) >= MIN_FAIL else ub_pool
        nn[(r, tau, per)] = n
    return p, p_lcb, ub, nn


def waste(p_val, u_val, s):
    """無駄時間 = (1/p - 1) * u_bar + s"""
    if p_val <= 0:
        return float("inf")
    return (1.0/p_val - 1.0) * u_val + s


def period_at(r, t0_hour, shift_h):
    base = (pd.Timestamp("2026-05-20T00:00:00Z")
            + pd.Timedelta(hours=t0_hour + shift_h))
    return classify_period(base.astimezone(REGION_TZ[r]).hour)


def solve(strategy, t0, slack_h, p_min, tables, s, d,
          R_allowed=None, T_allowed=None, default_type="c6a.large"):
    p, p_lcb, ub, nn = tables
    R_allowed = R_allowed or REGIONS
    T_allowed = T_allowed or TYPES

    if strategy == "B0":
        cand_r, cand_tau, shifts = [DEFAULT_REGION], [default_type], [0]
    elif strategy == "B1":
        cand_r, cand_tau, shifts = ([DEFAULT_REGION], [default_type],
                                    range(int(slack_h)+1))
    elif strategy == "B2":
        cand_r, cand_tau, shifts = R_allowed, T_allowed, [0]
    else:   # B3 / B3-LCB / B4
        cand_r, cand_tau, shifts = R_allowed, T_allowed, range(int(slack_h)+1)

    sel = p_lcb if strategy == "B3-LCB" else p
    best, best_key = None, float("inf")
    for r, tau, sh in itertools.product(cand_r, cand_tau, shifts):
        per = period_at(r, t0, sh)
        key = (r, tau, per)
        if key not in p:
            continue
        if sel[key] < p_min:
            continue
        rank = waste(sel[key], ub[key], s)
        if rank < best_key:
            best_key = rank
            best = dict(region=r, itype=tau, shift=sh, period=per,
                        p=p[key], waste=waste(p[key], ub[key], s))
    return best


def main():
    df, ok, s = load()
    print("=" * 76)
    print("データ: N_succ={}, 中断={} ({:.1%}), s={:.2f}秒".format(
        len(ok), int(ok["int"].sum()), ok["int"].mean(), s*60))
    print("目的関数: 無駄時間 = (1/p - 1) * u_bar + s   [分]")
    print("=" * 76)

    d = 60
    tables = build_tables(ok, d)
    p, p_lcb, ub, nn = tables
    strategies = ["B0", "B1", "B2", "B3", "B3-LCB", "B4"]

    # ── 主表: タイプ固定 (c6a.large), slack を振る ──────────────────────
    print("\n### 戦略比較 (c6a.large固定, d=60分, p_min=0)")
    print("    到着時刻 t0 を 24 時間で平均した無駄時間 [分]\n")
    rows = []
    for st in strategies:
        row = {"戦略": st}
        for slack in [0, 3, 6, 12]:
            ws = []
            for t0 in range(24):
                sol = solve(st, t0, slack, 0.0, tables, s, d,
                            T_allowed=["c6a.large"], default_type="c6a.large")
                if sol:
                    ws.append(sol["waste"])
            row[f"slack={slack}h"] = np.mean(ws)
        rows.append(row)
    t = pd.DataFrame(rows).set_index("戦略")
    base = t.loc["B0"]
    disp = t.copy()
    for c in disp.columns:
        disp[c] = [f"{v:.2f} ({(v/base[c]-1)*100:+.0f}%)" for v in t[c]]
    print(disp.to_string())

    # ── 平均 p ───────────────────────────────────────────────────────────
    print("\n### 選ばれた条件の平均成功確率 p (c6a.large, d=60)\n")
    rows = []
    for st in strategies:
        row = {"戦略": st}
        for slack in [0, 3, 6, 12]:
            ps = []
            for t0 in range(24):
                sol = solve(st, t0, slack, 0.0, tables, s, d,
                            T_allowed=["c6a.large"], default_type="c6a.large")
                if sol:
                    ps.append(sol["p"])
            row[f"slack={slack}h"] = round(np.mean(ps), 4)
        rows.append(row)
    print(pd.DataFrame(rows).set_index("戦略").to_string())

    # ── 寄与の分離 ───────────────────────────────────────────────────────
    print("\n### 寄与の分離 (c6a.large, d=60, slack=6h)\n")
    res = {}
    for st in ["B0", "B1", "B2", "B3"]:
        ws = [solve(st, t0, 6, 0.0, tables, s, d,
                    T_allowed=["c6a.large"], default_type="c6a.large")["waste"]
              for t0 in range(24)]
        res[st] = np.mean(ws)
    print(f"  B0 (何も選ばない)      : {res['B0']:.2f}分")
    print(f"  B1 (時刻のみ)          : {res['B1']:.2f}分  "
          f"時刻の寄与 = {res['B0']-res['B1']:.2f}分 ({(res['B1']/res['B0']-1)*100:+.0f}%)")
    print(f"  B2 (リージョンのみ)    : {res['B2']:.2f}分  "
          f"条件の寄与 = {res['B0']-res['B2']:.2f}分 ({(res['B2']/res['B0']-1)*100:+.0f}%)")
    print(f"  B3 (両方)              : {res['B3']:.2f}分  "
          f"合計     = {res['B0']-res['B3']:.2f}分 ({(res['B3']/res['B0']-1)*100:+.0f}%)")

    # ── タイプも自由にした場合 ───────────────────────────────────────────
    print("\n### タイプも選択可能にした場合 (d=60, slack=6h)\n")
    for st in ["B0", "B2", "B3"]:
        ws, ch = [], []
        for t0 in range(24):
            sol = solve(st, t0, 6, 0.0, tables, s, d)
            ws.append(sol["waste"])
            ch.append((REGION_LABELS[sol["region"]], sol["itype"], sol["period"]))
        print(f"  {st}: {np.mean(ws):.2f}分")
        if st == "B3":
            vc = pd.Series([f"{a} / {b}" for a, b, _ in ch]).value_counts()
            print("     選択された条件:")
            for k_, v in vc.items():
                print(f"       {k_:28s} {v:2d}/24")

    # ── 期限 d を振る ────────────────────────────────────────────────────
    print("\n### 期限 d による効果の違い (c6a.large, slack=6h)\n")
    rows = []
    for dd in [5, 10, 30, 60]:
        tb = build_tables(ok, dd)
        r = {"d": f"{dd}分"}
        for st in ["B0", "B3"]:
            ws = [solve(st, t0, 6, 0.0, tb, s, dd,
                        T_allowed=["c6a.large"], default_type="c6a.large")["waste"]
                  for t0 in range(24)]
            r[st] = round(np.mean(ws), 3)
        r["削減"] = f"{(r['B3']/r['B0']-1)*100:+.0f}%"
        rows.append(r)
    print(pd.DataFrame(rows).set_index("d").to_string())

    # ── p_min の影響 ─────────────────────────────────────────────────────
    print("\n### 信頼性下限 p_min の影響 (c6a.large, d=60, slack=6h)\n")
    rows = []
    for pm in [0.0, 0.8, 0.9, 0.95]:
        ws, feas = [], 0
        for t0 in range(24):
            sol = solve("B3", t0, 6, pm, tables, s, d,
                        T_allowed=["c6a.large"], default_type="c6a.large")
            if sol:
                feas += 1
                ws.append(sol["waste"])
        rows.append({"p_min": pm, "無駄時間": round(np.mean(ws), 2),
                     "実行可能": f"{feas}/24"})
    print(pd.DataFrame(rows).set_index("p_min").to_string())

    # ── 実機実験の予測値 ─────────────────────────────────────────────────
    print("\n" + "=" * 76)
    print("実機実験で検証すべき予測値 (c6a.large, d=60, slack=6h)")
    print("=" * 76)
    b0 = solve("B0", 0, 6, 0.0, tables, s, d,
               T_allowed=["c6a.large"], default_type="c6a.large")
    ps0 = np.mean([solve("B0", t, 6, 0.0, tables, s, d,
                         T_allowed=["c6a.large"], default_type="c6a.large")["p"]
                   for t in range(24)])
    ps3 = np.mean([solve("B3", t, 6, 0.0, tables, s, d,
                         T_allowed=["c6a.large"], default_type="c6a.large")["p"]
                   for t in range(24)])
    print(f"  完了率 p   : B0 {ps0:.3f} -> B3 {ps3:.3f}  (+{(ps3-ps0)*100:.1f}pt)")
    print(f"  無駄時間   : B0 {res['B0']:.2f}分 -> B3 {res['B3']:.2f}分  "
          f"({(res['B3']/res['B0']-1)*100:+.0f}%)")
    print(f"  やり直し率 : B0 {(1-ps0)*100:.1f}% -> B3 {(1-ps3)*100:.1f}%")
    n_needed = int(np.ceil(16*0.1*0.9/((ps3-ps0)**2))) if ps3 > ps0 else 0
    print(f"\n  完了率の差を検出するのに必要な標本数(概算, 両群計): {n_needed} 件")


if __name__ == "__main__":
    main()
