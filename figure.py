#!/usr/bin/env python3
import glob
from zoneinfo import ZoneInfo
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

DATA_DIR = "data"
T_MINUTES = 60

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
    "us-east-1":      "Virginia",
}

PERIOD_ORDER = ["Night", "Morning", "Afternoon", "Evening"]

def classify_period(local_hour: int) -> str:
    if local_hour < 6:
        return "Night"       # 00:00–05:59
    elif local_hour < 12:
        return "Morning"     # 06:00–11:59
    elif local_hour < 18:
        return "Afternoon"   # 12:00–17:59
    else:
        return "Evening"     # 18:00–23:59

# ── Load & filter ────────────────────────────────────────────────────────────
dfs = [pd.read_csv(f) for f in glob.glob(f"{DATA_DIR}/*.csv")]
df = pd.concat(dfs, ignore_index=True)

# F_comp is defined only over successfully launched instances (N_succ)
df = df[~df["launch_failed"].astype(bool)].reset_index(drop=True)

# ── Derive local time period from launch_time (UTC) ─────────────────────────
df["launch_dt_utc"] = pd.to_datetime(df["launch_time"], utc=True)
df["local_hour"] = df.apply(
    lambda r: r["launch_dt_utc"].astimezone(REGION_TZ[r["region"]]).hour, axis=1
)
df["time_period"] = df["local_hour"].apply(classify_period)

# ── F_comp(T) ────────────────────────────────────────────────────────────────
df["completed"] = ~df["interrupted"].astype(bool)

grouped = (
    df.groupby(["region", "instance_type", "time_period"])["completed"]
    .agg(["sum", "count"])
    .reset_index()
)
grouped["f_comp"] = grouped["sum"] / grouped["count"]

# ── Build pivot ───────────────────────────────────────────────────────────────
region_order   = ["ap-northeast-1", "ap-southeast-1", "eu-west-1", "us-east-1"]
instance_order = ["t3.micro", "c6a.large", "g4dn.xlarge"]

grouped["col_label"] = grouped.apply(
    lambda r: f"{REGION_LABELS[r['region']]}\n{r['instance_type']}", axis=1
)
col_order = [
    f"{REGION_LABELS[r]}\n{i}"
    for r in region_order
    for i in instance_order
]

pivot       = grouped.pivot(index="time_period", columns="col_label", values="f_comp")
count_pivot = grouped.pivot(index="time_period", columns="col_label", values="count")
sum_pivot   = grouped.pivot(index="time_period", columns="col_label", values="sum")

pivot       = pivot.reindex(index=PERIOD_ORDER, columns=col_order)
count_pivot = count_pivot.reindex(index=PERIOD_ORDER, columns=col_order)
sum_pivot   = sum_pivot.reindex(index=PERIOD_ORDER, columns=col_order)

# ── Annotation ────────────────────────────────────────────────────────────────
annot = pd.DataFrame(index=PERIOD_ORDER, columns=col_order, dtype=str)
for row in PERIOD_ORDER:
    for col in col_order:
        v = pivot.loc[row, col]
        if pd.isna(v):
            annot.loc[row, col] = "N/A"
        else:
            n = int(count_pivot.loc[row, col])
            s = int(sum_pivot.loc[row, col])
            annot.loc[row, col] = f"{v:.2f}\n({s}/{n})"

# ── Draw heatmap ──────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 4.5))

sns.heatmap(
    pivot.astype(float),
    annot=annot,
    fmt="",
    cmap="RdYlGn",
    vmin=0,
    vmax=1,
    linewidths=0.5,
    ax=ax,
    cbar_kws={"label": f"F_comp({T_MINUTES}) — P(no interruption in {T_MINUTES} min)"},
)

ax.set_title(
    f"Figure 1: Region / Instance type × Time period heatmap for F_comp({T_MINUTES})",
    fontsize=12,
    pad=12,
)
ax.set_xlabel("Region × Instance type", fontsize=10)
ax.set_ylabel("Local time period", fontsize=10)
ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
ax.set_xticklabels(ax.get_xticklabels(), rotation=0, fontsize=8)

for i in range(1, len(region_order)):
    ax.axvline(x=i * len(instance_order), color="black", linewidth=1.5)

plt.tight_layout()
plt.savefig("figure1_fcomp60_heatmap.png", dpi=150, bbox_inches="tight")
plt.show()
print("Saved: figure1_fcomp60_heatmap.png")
