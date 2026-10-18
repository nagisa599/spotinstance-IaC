#!/usr/bin/env python3
"""v3 (実行条件選択モデル) 用の図を生成する.

figure6_strategy.png : slack に対する戦略別の無駄時間
figure7_period.png   : 時間帯別の p と無駄時間 (N.Virginia c6a.large)
figure8_deadline.png : 期限 d による効果の違い
"""
import matplotlib.pyplot as plt
import numpy as np

import strategy2 as S

PERIODS = S.PERIODS
C_B0, C_B1, C_B2 = "#C1554E", "#2E5E8E", "#3E8A7A"


def fig_strategy(ok, s):
    """slack に対する B0/B1 の無駄時間."""
    tables = S.build_tables(ok, 60)
    slacks = [0, 1, 2, 3, 4, 6, 8, 12]
    res = {st: [] for st in ["B0", "B1"]}
    for st in res:
        for sl in slacks:
            ws = [S.solve(st, t0, sl, 0.0, tables, s, 60,
                          T_allowed=["c6a.large"],
                          default_type="c6a.large")["waste"]
                  for t0 in range(24)]
            res[st].append(np.mean(ws))

    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.plot(slacks, res["B0"], "o--", color=C_B0, lw=1.8, ms=5,
            label="B0: 条件を選ばない")
    ax.plot(slacks, res["B1"], "o-", color=C_B1, lw=2.0, ms=5,
            label="B1: 実行時刻を選ぶ")
    ax.fill_between(slacks, res["B1"], res["B0"], color=C_B1, alpha=0.10)
    i = slacks.index(6)
    ax.annotate(f"{(res['B1'][i]/res['B0'][i]-1)*100:.0f}%",
                xy=(6, (res["B0"][i]+res["B1"][i])/2),
                xytext=(7.2, (res["B0"][i]+res["B1"][i])/2 + 0.35),
                fontsize=10, color=C_B1,
                arrowprops=dict(arrowstyle="-", color=C_B1, lw=0.8))
    ax.set_xlabel("Allowed delay (slack) [hours]")
    ax.set_ylabel("Wasted time [min]")
    ax.set_ylim(0, max(res["B0"]) * 1.15)
    ax.set_xticks(slacks)
    ax.legend(frameon=False, fontsize=9, prop={"family": "Hiragino Sans"})
    ax.grid(alpha=0.2, lw=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig("images/figure6_strategy.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("Saved: images/figure6_strategy.png")


def fig_period(ok, s):
    """N.Virginia c6a.large の時間帯別 p と無駄時間."""
    p, plcb, ub, nn = S.build_tables(ok, 60)
    r = "us-east-1"
    ps = [p[(r, "c6a.large", q)] for q in PERIODS]
    ws = [(1/p[(r, "c6a.large", q)] - 1) * ub[(r, "c6a.large", q)] + s
          for q in PERIODS]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.5, 3.4))
    x = np.arange(len(PERIODS))

    cols = [C_B1 if v == max(ps) else (C_B0 if v == min(ps) else "#8A93A0")
            for v in ps]
    a1.bar(x, ps, color=cols, edgecolor="#36506B", lw=0.7)
    a1.set_ylim(0, 1.08)
    a1.set_ylabel("$F_{comp}(60)$")
    a1.set_xticks(x); a1.set_xticklabels(PERIODS, fontsize=9)
    for i, v in enumerate(ps):
        a1.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=9)
    a1.spines[["top", "right"]].set_visible(False)

    cols2 = [C_B0 if v == max(ws) else (C_B1 if v == min(ws) else "#8A93A0")
             for v in ws]
    a2.bar(x, ws, color=cols2, edgecolor="#36506B", lw=0.7)
    a2.set_ylabel("Wasted time [min]")
    a2.set_xticks(x); a2.set_xticklabels(PERIODS, fontsize=9)
    for i, v in enumerate(ws):
        a2.text(i, v + max(ws)*0.03, f"{v:.2f}", ha="center", fontsize=9)
    a2.set_ylim(0, max(ws) * 1.18)
    a2.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    plt.savefig("images/figure7_period.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("Saved: images/figure7_period.png")


def fig_deadline(ok, s):
    """期限 d による B0/B1 の差."""
    ds = [5, 10, 30, 60]
    b0, b1 = [], []
    for d in ds:
        tb = S.build_tables(ok, d)
        for st, acc in (("B0", b0), ("B1", b1)):
            ws = [S.solve(st, t0, 6, 0.0, tb, s, d,
                          T_allowed=["c6a.large"],
                          default_type="c6a.large")["waste"]
                  for t0 in range(24)]
            acc.append(np.mean(ws))

    fig, ax = plt.subplots(figsize=(7, 3.6))
    w = 0.36
    x = np.arange(len(ds))
    ax.bar(x - w/2, b0, w, color=C_B0, label="B0: 条件を選ばない",
           edgecolor="#8A3A34", lw=0.7)
    ax.bar(x + w/2, b1, w, color=C_B1, label="B1: 実行時刻を選ぶ",
           edgecolor="#1E4068", lw=0.7)
    for i in range(len(ds)):
        ax.text(i, max(b0[i], b1[i]) + max(b0)*0.04,
                f"{(b1[i]/b0[i]-1)*100:.0f}%", ha="center",
                fontsize=9, color=C_B1)
    ax.set_xticks(x); ax.set_xticklabels([f"{d} min" for d in ds])
    ax.set_xlabel("Workload deadline $d$")
    ax.set_ylabel("Wasted time [min]")
    ax.set_ylim(0, max(b0) * 1.2)
    ax.legend(frameon=False, fontsize=9, prop={"family": "Hiragino Sans"})
    ax.grid(axis="y", alpha=0.2, lw=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig("images/figure8_deadline.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("Saved: images/figure8_deadline.png")


if __name__ == "__main__":
    plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
    df, ok, s = S.load()
    print(f"N_succ={len(ok)}, s={s*60:.2f}s")
    fig_strategy(ok, s)
    fig_period(ok, s)
    fig_deadline(ok, s)
