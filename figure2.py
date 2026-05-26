#!/usr/bin/env python3
import glob
from zoneinfo import ZoneInfo
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

DATA_DIR = "data"
DEADLINES = [5, 10, 30, 60]
DATE_START = "2026-05-19T00:00:00Z"
DATE_END   = "2026-05-26T00:00:00Z"

# Top-4 combinations by time-period spread in F_comp(60)
PANELS = [
    {"region": "us-east-1",      "instance_type": "c6a.large",   "label": "(a) N. Virginia — c6a.large"},
    {"region": "eu-west-1",      "instance_type": "c6a.large",   "label": "(b) Ireland — c6a.large"},
    {"region": "ap-northeast-1", "instance_type": "g4dn.xlarge", "label": "(c) Tokyo — g4dn.xlarge"},
    {"region": "ap-southeast-1", "instance_type": "g4dn.xlarge", "label": "(d) Singapore — g4dn.xlarge"},
]

PERIOD_ORDER = ["Night", "Morning", "Afternoon", "Evening"]
PERIOD_STYLES = {
    "Night":     {"color": "#0D47A1", "marker": "o", "ls": "-",           "lw": 2.5, "ms": 9},
    "Morning":   {"color": "#E65100", "marker": "s", "ls": "--",          "lw": 2.5, "ms": 9},
    "Afternoon": {"color": "#1B5E20", "marker": "^", "ls": "-.",          "lw": 2.5, "ms": 9},
    "Evening":   {"color": "#880E4F", "marker": "D", "ls": (0,(3,1,1,1)), "lw": 2.5, "ms": 8},
}

REGION_TZ = {
    "ap-northeast-1": ZoneInfo("Asia/Tokyo"),
    "ap-southeast-1": ZoneInfo("Asia/Singapore"),
    "eu-west-1":      ZoneInfo("Europe/Dublin"),
    "us-east-1":      ZoneInfo("America/New_York"),
}

def classify_period(h):
    if h < 6:    return "Night"
    elif h < 12: return "Morning"
    elif h < 18: return "Afternoon"
    else:        return "Evening"

# ── Load & filter ─────────────────────────────────────────────────────────────
dfs = [pd.read_csv(f) for f in glob.glob(f"{DATA_DIR}/*.csv")]
df = pd.concat(dfs, ignore_index=True)
df = df[(df["timestamp"] >= DATE_START) & (df["timestamp"] < DATE_END)].reset_index(drop=True)
df = df[~df["launch_failed"].astype(bool)].reset_index(drop=True)
df["interrupted"] = df["interrupted"].astype(bool)

df["launch_dt_utc"] = pd.to_datetime(df["launch_time"], utc=True)
df["local_hour"] = df.apply(
    lambda r: r["launch_dt_utc"].astimezone(REGION_TZ[r["region"]]).hour, axis=1
)
df["time_period"] = df["local_hour"].apply(classify_period)

# ── Compute F_comp(d) ─────────────────────────────────────────────────────────
records = []
for panel in PANELS:
    region, itype = panel["region"], panel["instance_type"]
    for period in PERIOD_ORDER:
        sub = df[
            (df["region"] == region) &
            (df["instance_type"] == itype) &
            (df["time_period"] == period)
        ]
        n_succ = len(sub)
        if n_succ == 0:
            continue
        for d in DEADLINES:
            n_int = ((sub["interrupted"]) & (sub["uptime_s"] < d * 60)).sum()
            records.append({
                "region": region, "instance_type": itype,
                "time_period": period, "deadline_min": d,
                "f_comp": 1 - n_int / n_succ,
            })

results = pd.DataFrame(records)

# ── Style ─────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family":       "DejaVu Sans",
    "font.size":         11,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.color":        "#E0E0E0",
    "grid.linewidth":    0.8,
    "axes.facecolor":    "white",
    "figure.facecolor":  "white",
})

fig, axes = plt.subplots(
    2, 2,
    figsize=(10, 7),
    gridspec_kw={"hspace": 0.42, "wspace": 0.28},
)
axes_flat = [axes[0,0], axes[0,1], axes[1,0], axes[1,1]]

# Per-row y limits (row 0 = c6a.large, row 1 = g4dn.xlarge)
row_data = {
    0: results[results["instance_type"] == "c6a.large"]["f_comp"],
    1: results[results["instance_type"] == "g4dn.xlarge"]["f_comp"],
}
row_ylim = {}
for ri, data in row_data.items():
    y_lo = max(0.0, np.floor(data.min() * 20) / 20 - 0.02)
    row_ylim[ri] = (y_lo, 1.025)

for idx, (ax, panel) in enumerate(zip(axes_flat, PANELS)):
    region, itype = panel["region"], panel["instance_type"]
    ri = idx // 2

    sub = results[
        (results["region"] == region) &
        (results["instance_type"] == itype)
    ]

    for period in PERIOD_ORDER:
        row = sub[sub["time_period"] == period].sort_values("deadline_min")
        if row.empty:
            continue
        p = PERIOD_STYLES[period]
        ax.plot(
            row["deadline_min"], row["f_comp"],
            color=p["color"], marker=p["marker"],
            linestyle=p["ls"], linewidth=p["lw"], markersize=p["ms"],
            label=period, zorder=3,
        )

    ax.axhline(1.0, color="#CCCCCC", linewidth=0.9, linestyle="--", zorder=1)

    ax.set_title(panel["label"], fontsize=12, fontweight="bold", loc="left", pad=7)
    ax.set_xscale("log")
    ax.set_xticks(DEADLINES)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{int(v)}"))
    ax.set_xlim(3.5, 75)
    ax.set_ylim(*row_ylim[ri])
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f"))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.05))
    ax.tick_params(axis="both", labelsize=10)

    ax.set_xlabel("Workload deadline (min)", fontsize=11)
    ax.set_ylabel(r"$F_\mathrm{comp}(d)$", fontsize=12)

# Shared legend
handles, labels = axes_flat[0].get_legend_handles_labels()
fig.legend(
    handles, labels,
    loc="lower center",
    ncol=4,
    fontsize=11,
    frameon=True,
    framealpha=1.0,
    edgecolor="#BBBBBB",
    title="Local time period",
    title_fontsize=10,
    bbox_to_anchor=(0.5, -0.04),
    handlelength=2.5,
)


plt.savefig("images/figure2_fcomp_multiregion.png", dpi=180, bbox_inches="tight")
plt.show()
print("Saved: images/figure2_fcomp_multiregion.png")
