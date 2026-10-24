#!/usr/bin/env python3
"""comsys/main.tex 用の図 (日本語版) を生成する.

figures/figure1_fcomp60_heatmap.png : リージョン×インスタンスタイプ×時間帯別の F_comp(60)
figures/figure3_hazard.png          : 経過時間別の中断ハザード率

ロジックはリポジトリ直下の figure.py / figure3.py と同じで,
期間を本測定 (5月+10月の15日合算, 起動リクエスト4,320件) にしている.
"""
import glob
import os
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
OUT_DIR = os.path.join(HERE, "figures")

# [start, end) UTC. 10月は SPS 記録開始の 08:00 から 192 時間.
PERIODS_UTC = [
    ("2026-05-19T00:00:00Z", "2026-05-26T00:00:00Z"),
    ("2026-10-10T00:00:00Z", "2026-10-18T08:00:00Z"),
]

plt.rcParams["font.family"] = "Hiragino Sans"

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
PERIOD_ORDER = ["Night", "Morning", "Afternoon", "Evening"]
REGION_ORDER = ["us-east-1", "eu-west-1", "ap-northeast-1", "ap-southeast-1"]
INSTANCE_ORDER = ["c6a.large", "g4dn.xlarge", "t3.micro"]


def classify_period(h):
    return ("Night" if h < 6 else "Morning" if h < 12
            else "Afternoon" if h < 18 else "Evening")


def load():
    """起動に成功したインスタンスのみを返す (F_comp とハザード率の分母は N_succ)."""
    df = pd.concat([pd.read_csv(f) for f in glob.glob(f"{DATA_DIR}/*.csv")],
                   ignore_index=True).drop_duplicates(subset="run_id")
    in_period = np.zeros(len(df), dtype=bool)
    for start, end in PERIODS_UTC:
        in_period |= (df["timestamp"] >= start) & (df["timestamp"] < end)
    df = df[in_period].reset_index(drop=True)
    print(f"N_req = {len(df)}")
    ok = df[~df["launch_failed"].astype(bool)].reset_index(drop=True)
    print(f"N_succ = {len(ok)}")
    ok["int"] = ok["interrupted"].astype(bool)
    ok["u"] = ok["uptime_s"].astype(float) / 60.0
    return ok


# ── 図: F_comp(60) ヒートマップ ──────────────────────────────────────────────
def fig_heatmap(ok, T_minutes=60):
    df = ok.copy()
    launch = pd.to_datetime(df["launch_time"], utc=True)
    df["time_period"] = [classify_period(t.astimezone(REGION_TZ[r]).hour)
                         for t, r in zip(launch, df["region"])]
    df["col_label"] = [f"{REGION_LABELS[r]}\n{i}"
                       for r, i in zip(df["region"], df["instance_type"])]
    col_order = [f"{REGION_LABELS[r]}\n{i}"
                 for r in REGION_ORDER for i in INSTANCE_ORDER]

    # 中断されなかった, または T 分以上稼働してから中断されたものを完了とみなす
    completed = (~df["int"]) | (df["uptime_s"] >= T_minutes * 60)
    g = completed.groupby([df["time_period"], df["col_label"]]).agg(["sum", "count"])
    s = g["sum"].unstack().reindex(index=PERIOD_ORDER, columns=col_order)
    n = g["count"].unstack().reindex(index=PERIOD_ORDER, columns=col_order)
    f = s / n
    annot = f.copy().astype(object)
    for row in PERIOD_ORDER:
        for col in col_order:
            annot.loc[row, col] = (f"{f.loc[row, col]:.2f}\n"
                                   f"({int(s.loc[row, col])}/{int(n.loc[row, col])})")

    fig, ax = plt.subplots(figsize=(14, 4.5))
    sns.heatmap(f.astype(float), annot=annot, fmt="", cmap="RdYlGn",
                vmin=0, vmax=1, linewidths=0.5, ax=ax,
                cbar_kws={"label": rf"$F_\mathrm{{comp}}({T_minutes})$"})
    ax.set_xlabel("リージョン × インスタンスタイプ", fontsize=10)
    ax.set_ylabel("時間帯（ローカル時刻）", fontsize=10)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    ax.set_xticklabels(ax.get_xticklabels(), rotation=0, fontsize=8)
    for i in range(1, len(REGION_ORDER)):
        ax.axvline(x=i * len(INSTANCE_ORDER), color="black", linewidth=1.5)

    plt.tight_layout()
    out = os.path.join(OUT_DIR, f"figure1_fcomp{T_minutes}_heatmap.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


# ── 図: ハザード率 ───────────────────────────────────────────────────────────
def fig_hazard(ok):
    bins = [(0, 5), (5, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60)]
    centers, rates, counts = [], [], []
    for lo, hi in bins:
        c = int(((ok["int"]) & (ok["u"] >= lo) & (ok["u"] < hi)).sum())
        risk = int(((~ok["int"]) | (ok["u"] >= lo)).sum())
        centers.append((lo + hi) / 2)
        rates.append(c / risk / (hi - lo) * 100)
        counts.append(c)
    print(f"interruptions per bin = {counts} (total {sum(counts)})")

    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    ax.bar(centers, rates, width=[hi-lo-0.8 for lo, hi in bins],
           color="#6B8EAD", edgecolor="#36506B", linewidth=0.8)
    mean = np.average(rates, weights=[hi-lo for lo, hi in bins])
    ax.axhline(mean, color="#C1554E", linestyle="--", linewidth=1.4,
               label=f"平均 {mean:.3f} %/分")
    for x, y, c in zip(centers, rates, counts):
        ax.text(x, y + 0.006, f"n={c}", ha="center", fontsize=7.5, color="#444")

    ax.set_xlabel("起動からの経過時間（分）")
    ax.set_ylabel("ハザード率（%/分）")
    ax.set_ylim(0, max(rates) * 1.30)
    ax.set_xticks([0, 10, 20, 30, 40, 50, 60])
    ax.legend(frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    out = os.path.join(OUT_DIR, "figure3_hazard.png")
    plt.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


if __name__ == "__main__":
    ok = load()
    fig_heatmap(ok)
    fig_hazard(ok)
