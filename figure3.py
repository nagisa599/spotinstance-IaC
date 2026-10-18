#!/usr/bin/env python3
"""修論の新規章 (分割粒度) 用の図を生成する.

figure3_hazard.png   : 中断ハザード率が経過時間によらずほぼ一定であること
figure4_ucurve.png   : 分割数 k に対する総無駄時間の U 字カーブと c 感度
figure5_period_k.png : 時間帯 x 分割数 のヒートマップ
"""
import glob
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

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
PERIODS = ["Night", "Morning", "Afternoon", "Evening"]


def classify_period(h):
    return ("Night" if h < 6 else "Morning" if h < 12
            else "Afternoon" if h < 18 else "Evening")


def load():
    df = pd.concat([pd.read_csv(f) for f in glob.glob(f"{DATA_DIR}/*.csv")],
                   ignore_index=True).drop_duplicates(subset="run_id")
    df = df[(df["timestamp"] >= DATE_START) & (df["timestamp"] < DATE_END)]
    df = df.reset_index(drop=True)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    df["period"] = [classify_period(t.astimezone(REGION_TZ[r]).hour)
                    for t, r in zip(ts, df["region"])]
    df["lf"] = df["launch_failed"].astype(bool)
    ok = df[~df["lf"]].copy()
    ok["int"] = ok["interrupted"].astype(bool)
    ok["u"] = ok["uptime_s"].astype(float) / 60.0
    return df, ok


def wilson_lcb(k, n):
    if n == 0:
        return 0.0
    ph = k / n
    return max(0.0, (ph + Z**2 / (2*n)
                     - Z*np.sqrt(ph*(1-ph)/n + Z**2/(4*n**2))) / (1 + Z**2/n))


def p_and_ubar(sub, T):
    """期限 T に対する完了確率(LCB)と、中断時の平均損失."""
    n = len(sub)
    k = int(((~sub["int"]) | (sub["u"] >= T)).sum())
    f = sub[sub["int"] & (sub["u"] < T)]
    return wilson_lcb(k, n), (f["u"].mean() if len(f) else 0.0)


def waste(sub, k, s_min):
    """分割数 k のときの総無駄時間 (分)."""
    T = 60.0 / k
    p, ub = p_and_ubar(sub, T)
    return k * (1.0/p - 1.0) * ub + k * s_min


# ── 図3: ハザード率 ──────────────────────────────────────────────────────────
def fig_hazard(ok):
    bins = [(0, 5), (5, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60)]
    centers, rates, counts = [], [], []
    for lo, hi in bins:
        c = int(((ok["int"]) & (ok["u"] >= lo) & (ok["u"] < hi)).sum())
        risk = int(((~ok["int"]) | (ok["u"] >= lo)).sum())
        centers.append((lo + hi) / 2)
        rates.append(c / risk / (hi - lo) * 100)
        counts.append(c)

    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    ax.bar(centers, rates, width=[hi-lo-0.8 for lo, hi in bins],
           color="#6B8EAD", edgecolor="#36506B", linewidth=0.8)
    mean = np.average(rates, weights=[hi-lo for lo, hi in bins])
    ax.axhline(mean, color="#C1554E", linestyle="--", linewidth=1.4,
               label=f"mean = {mean:.3f} %/min")
    for x, y, c in zip(centers, rates, counts):
        ax.text(x, y + 0.006, f"n={c}", ha="center", fontsize=7.5, color="#444")

    ax.set_xlabel("Elapsed time since launch (min)")
    ax.set_ylabel("Hazard rate (%/min)")
    ax.set_ylim(0, max(rates) * 1.30)
    ax.set_xticks([0, 10, 20, 30, 40, 50, 60])
    ax.legend(frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig("images/figure3_hazard.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("Saved: images/figure3_hazard.png")


# ── 図4: U字カーブと c 感度 ──────────────────────────────────────────────────
def fig_ucurve(ok, s_launch_min):
    ks = [1, 2, 3, 4, 6, 10, 12, 20]
    cs = [0, 5, 10, 30, 60]
    colors = ["#2E5E8E", "#3E8A7A", "#B5892F", "#C1554E", "#7A5A98"]

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for c, col in zip(cs, colors):
        s = s_launch_min + c / 60.0
        ys = [waste(ok, k, s) for k in ks]
        ax.plot(ks, ys, "o-", color=col, linewidth=1.8, markersize=5,
                label=f"c = {c} s")
        kstar = ks[int(np.argmin(ys))]
        ax.plot(kstar, min(ys), "o", color=col, markersize=11,
                markerfacecolor="none", markeredgewidth=2.0)

    ax.set_xlabel("Number of segments $k$")
    ax.set_ylabel("Total wasted time (min)")
    ax.set_xscale("log")
    ax.set_xticks(ks)
    ax.set_xticklabels(ks)
    ax.set_ylim(0, 8)
    ax.legend(frameon=False, fontsize=9, title="checkpoint cost",
              title_fontsize=9)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig("images/figure4_ucurve.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("Saved: images/figure4_ucurve.png")


# ── 図5: 時間帯 x 分割数 ─────────────────────────────────────────────────────
def fig_period_k(ok, s_launch_min):
    ks = [1, 2, 4, 6, 12]
    mat = pd.DataFrame(index=PERIODS, columns=[f"k={k}" for k in ks],
                       dtype=float)
    for p_ in PERIODS:
        sub = ok[ok["period"] == p_]
        for k in ks:
            mat.loc[p_, f"k={k}"] = waste(sub, k, s_launch_min)

    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    sns.heatmap(mat.astype(float), annot=True, fmt=".2f", cmap="RdYlGn_r",
                linewidths=0.6, ax=ax,
                cbar_kws={"label": "Wasted time (min)"})
    ax.set_xlabel("Number of segments")
    ax.set_ylabel("Local time period")
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    plt.tight_layout()
    plt.savefig("images/figure5_period_k.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("Saved: images/figure5_period_k.png")


if __name__ == "__main__":
    df, ok = load()
    s_launch = df[~df["lf"]]["startup_s"].astype(float).mean() / 60.0
    print(f"N_succ={len(ok)}, interrupted={int(ok['int'].sum())}, "
          f"s={s_launch*60:.2f}s")
    fig_hazard(ok)
    fig_ucurve(ok, s_launch)
    fig_period_k(ok, s_launch)
