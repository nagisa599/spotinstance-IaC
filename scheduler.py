#!/usr/bin/env python3
"""実行条件選択モデルのスケジューラ.

既存の観測データ (data/*.csv) から F_comp と u_bar のテーブルを作り、
到着時刻 t0 に対して「いつ起動すべきか」を決定する。

Lambda から import して使うことを想定し、テーブルは JSON に書き出す
(Lambda 内で pandas を使わなくて済むようにする)。

使い方:
  python3 scheduler.py --build          # テーブルを model_table.json に書き出す
  python3 scheduler.py --decide 9       # UTC 9時に到着したジョブの実行時刻を決める
  python3 scheduler.py --plan           # 24時刻ぶんの決定を一覧表示
"""
import argparse
import glob
import json
import os
from zoneinfo import ZoneInfo

DATA_DIR = "data"
TABLE_PATH = "model_table.json"
Z = 1.96

REGION_TZ = {
    "ap-northeast-1": "Asia/Tokyo",
    "ap-southeast-1": "Asia/Singapore",
    "eu-west-1":      "Europe/Dublin",
    "us-east-1":      "America/New_York",
}
PERIODS = ["Night", "Morning", "Afternoon", "Evening"]

# 実験1の設定: リージョンとタイプは固定し、時刻のみ選択する
EXP_REGION = "us-east-1"
EXP_TYPE = "c6a.large"
EXP_DEADLINE = 60      # d [分]
EXP_SLACK_H = 6        # D - d [時間]


def classify_period(h):
    return ("Night" if h < 6 else "Morning" if h < 12
            else "Afternoon" if h < 18 else "Evening")


def wilson_lcb(k, n):
    """Wilson 95% 下側信頼限界。標本が少ないセルを楽観視しないため。"""
    if n == 0:
        return 0.0
    import math
    ph = k / n
    return max(0.0, (ph + Z**2/(2*n)
                     - Z*math.sqrt(ph*(1-ph)/n + Z**2/(4*n**2))) / (1 + Z**2/n))


# ── テーブル構築 (観測データ -> JSON) ────────────────────────────────────────
def build_table(out_path=TABLE_PATH):
    import pandas as pd

    df = pd.concat([pd.read_csv(f) for f in glob.glob(f"{DATA_DIR}/*.csv")],
                   ignore_index=True).drop_duplicates(subset="run_id")
    df = df[(df["timestamp"] >= "2026-05-19T00:00:00Z")
            & (df["timestamp"] < "2026-05-26T00:00:00Z")]
    ok = df[~df["launch_failed"].astype(bool)].copy()

    dt = pd.to_datetime(ok["launch_time"], utc=True)
    ok["period"] = [classify_period(d.astimezone(ZoneInfo(REGION_TZ[r])).hour)
                    for d, r in zip(dt, ok["region"])]
    ok["int"] = ok["interrupted"].astype(bool)
    ok["u"] = ok["uptime_s"].astype(float) / 60.0

    d = EXP_DEADLINE
    # u_bar は中断例が少ないとゼロに潰れるので、全体プール値で補完する
    pool = ok[ok["int"] & (ok["u"] < d)]["u"].mean()

    table = {"deadline": d, "startup_s": float(ok["startup_s"].mean()),
             "cells": {}}
    for (r, tau, per), g in ok.groupby(["region", "instance_type", "period"]):
        n = len(g)
        k = int(((~g["int"]) | (g["u"] >= d)).sum())
        f = g[g["int"] & (g["u"] < d)]
        table["cells"][f"{r}|{tau}|{per}"] = {
            "n": n, "k": k,
            "p": k / n,
            "p_lcb": wilson_lcb(k, n),
            "u_bar": float(f["u"].mean()) if len(f) >= 3 else float(pool),
            "n_fail": len(f),
        }
    with open(out_path, "w") as fp:
        json.dump(table, fp, indent=2)
    print(f"Saved: {out_path}  ({len(table['cells'])} cells)")
    return table


def load_table(path=TABLE_PATH):
    with open(path) as fp:
        return json.load(fp)


# ── 意思決定 ────────────────────────────────────────────────────────────────
def waste(p, u, s_min):
    """無駄時間 = (1/p - 1) * u_bar + s"""
    if p <= 0:
        return float("inf")
    return (1.0/p - 1.0) * u + s_min


def period_at(region, t0_utc_hour, shift_h):
    """UTC 時刻 t0+shift における region のローカル時間帯."""
    import datetime
    base = datetime.datetime(2026, 5, 20, tzinfo=datetime.timezone.utc)
    t = base + datetime.timedelta(hours=t0_utc_hour + shift_h)
    return classify_period(t.astimezone(ZoneInfo(REGION_TZ[region])).hour)


def decide(t0_utc_hour, table, strategy="B1",
           region=EXP_REGION, itype=EXP_TYPE, slack_h=EXP_SLACK_H,
           use_lcb=True):
    """戦略に従って起動の遅延時間 (時間) を決める.

    B0: 遅延なし (到着時刻に即実行)
    B1: slack の範囲で無駄時間が最小となる時刻を選ぶ
    """
    s_min = table["startup_s"] / 60.0
    if strategy == "B0":
        shifts = [0]
    else:
        shifts = range(int(slack_h) + 1)

    best = None
    for sh in shifts:
        per = period_at(region, t0_utc_hour, sh)
        cell = table["cells"].get(f"{region}|{itype}|{per}")
        if cell is None:
            continue
        p_sel = cell["p_lcb"] if use_lcb else cell["p"]
        w = waste(p_sel, cell["u_bar"], s_min)
        if best is None or w < best["waste_sel"]:
            best = {
                "shift_h": sh, "period": per,
                "p": cell["p"], "p_lcb": cell["p_lcb"],
                "u_bar": cell["u_bar"],
                "waste_sel": w,
                "waste": waste(cell["p"], cell["u_bar"], s_min),
                "n": cell["n"], "n_fail": cell["n_fail"],
            }
    return best


def plan(table):
    """24時刻ぶんの決定を一覧表示し、B0 との比較を出す."""
    print(f"実験設定: {EXP_REGION} / {EXP_TYPE} / d={EXP_DEADLINE}分 / "
          f"slack={EXP_SLACK_H}h")
    print(f"起動オーバーヘッド s = {table['startup_s']:.2f}秒")
    print()
    print(f"{'到着(UTC)':>10}{'現地':>12}{'B0無駄':>9}"
          f"{'→ 遅延':>8}{'実行時間帯':>12}{'B1無駄':>9}{'削減':>8}")
    print("-" * 70)
    w0s, w1s, shifts = [], [], []
    for t0 in range(24):
        b0 = decide(t0, table, "B0")
        b1 = decide(t0, table, "B1")
        w0s.append(b0["waste"]); w1s.append(b1["waste"])
        shifts.append(b1["shift_h"])
        red = (b1["waste"]/b0["waste"] - 1) * 100 if b0["waste"] > 0 else 0
        print(f"{t0:>8}時{b0['period']:>12}{b0['waste']:>8.2f}分"
              f"{b1['shift_h']:>6}h{b1['period']:>12}"
              f"{b1['waste']:>8.2f}分{red:>7.0f}%")
    print("-" * 70)
    m0, m1 = sum(w0s)/24, sum(w1s)/24
    print(f"{'平均':>10}{'':>12}{m0:>8.2f}分{'':>6}{'':>12}"
          f"{m1:>8.2f}分{(m1/m0-1)*100:>7.0f}%")
    print()
    print(f"遅延なしで実行: {shifts.count(0)}/24 時刻 "
          f"({shifts.count(0)/24*100:.0f}%)")
    print(f"平均遅延: {sum(shifts)/24:.1f} 時間")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="テーブルを構築")
    ap.add_argument("--decide", type=int, metavar="HOUR",
                    help="指定UTC時刻に到着したジョブの実行時刻を決める")
    ap.add_argument("--plan", action="store_true", help="24時刻ぶんを一覧表示")
    a = ap.parse_args()

    if a.build:
        build_table()
        return
    if not os.path.exists(TABLE_PATH):
        print(f"{TABLE_PATH} がありません。--build を先に実行してください。")
        return
    table = load_table()

    if a.decide is not None:
        for st in ["B0", "B1"]:
            r = decide(a.decide, table, st)
            print(f"{st}: {a.decide}時到着 -> {r['shift_h']}時間後に実行 "
                  f"({r['period']}), p={r['p']:.3f} (n={r['n']}, "
                  f"中断{r['n_fail']}件), 無駄時間={r['waste']:.2f}分")
    elif a.plan:
        plan(table)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
