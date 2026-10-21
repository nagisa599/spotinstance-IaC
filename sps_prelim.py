#!/usr/bin/env python3
"""予備実験: SPS と起動後の継続性 (F_comp(60)) の関係を調べる.

入力: data/sps-*.csv (2026-10-10 ~ 2026-10-18 の測定)
出力: 論文の予備実験の章に載せる数値を標準出力に表示する.
"""
import glob

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.stats.contingency_tables import StratifiedTable

DATA_GLOB = "data/sps-*.csv"
DEADLINE_S = 3600
Z = 1.96

REGION_TZ = {
    "ap-northeast-1": "Asia/Tokyo",
    "ap-southeast-1": "Asia/Singapore",
    "eu-west-1":      "Europe/Dublin",
    "us-east-1":      "America/New_York",
}
PERIODS = ["Night", "Morning", "Afternoon", "Evening"]
# 各タイプで最も多く観測された SPS を通常値とし, それを下回る場合を「低下」とする
USUAL_SPS = {"c6a.large": 3, "g4dn.xlarge": 9, "t3.micro": 3}
TARGET_TYPES = ["c6a.large", "g4dn.xlarge"]  # t3.micro は SPS がほぼ一定で中断も 1 件のみ


def wilson(k, n, z=Z):
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def load():
    df = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(DATA_GLOB))], ignore_index=True)
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    # 最終時刻の起動はエクスポート時点で観測中のため除外する
    hour = df["ts"].dt.floor("h")
    df = df[hour < hour.max()].copy()
    df["local_hour"] = [t.tz_convert(REGION_TZ[r]).hour for t, r in zip(df["ts"], df["region"])]
    df["period"] = pd.cut(df["local_hour"], [0, 6, 12, 18, 24], right=False, labels=PERIODS).astype(str)
    df["sps_low"] = df["sps_score"] < df["instance_type"].map(USUAL_SPS)
    return df


def main():
    df = load()
    s = df[df["success"]].copy()
    s["int60"] = (s["interrupted"] & (s["uptime_s"] < DEADLINE_S)).astype(int)

    print(f"期間: {df['ts'].min()} -- {df['ts'].max()}")
    print(f"N_req={len(df)}, N_succ={len(s)}, 60分前の中断={s['int60'].sum()}")
    print("\nSPS の分布 (タイプ別)")
    print(pd.crosstab(df["instance_type"], df["sps_score"]))

    print("\n表: タイプ x SPS 区分ごとの起動成功率と F_comp(60)")
    for t in TARGET_TYPES:
        for low in (False, True):
            req = df[(df["instance_type"] == t) & (df["sps_low"] == low)]
            g = s[(s["instance_type"] == t) & (s["sps_low"] == low)]
            n, k = len(g), int((g["int60"] == 0).sum())
            lo, hi = wilson(k, n)
            label = "低下" if low else "通常"
            print(f"  {t:12s} {label}: 起動成功率={req['success'].mean():.3f} ({len(req)}件), "
                  f"F60={k / n:.2f} [{lo:.2f}, {hi:.2f}] (n={n}, 中断={n - k})")

    ct = s[s["instance_type"].isin(TARGET_TYPES)]

    tables = []
    for _, g in ct.groupby(["region", "instance_type"]):
        tables.append(np.array([
            [g[g["sps_low"]]["int60"].sum(), (g["sps_low"] & (g["int60"] == 0)).sum()],
            [g[~g["sps_low"]]["int60"].sum(), (~g["sps_low"] & (g["int60"] == 0)).sum()],
        ]))
    st = StratifiedTable(tables)
    lo, hi = st.oddsratio_pooled_confint()
    print(f"\nMantel-Haenszel オッズ比 (リージョン x タイプで層別): {st.oddsratio_pooled:.2f} "
          f"[{lo:.2f}, {hi:.2f}], p={st.test_null_odds().pvalue:.1e}, "
          f"均一性 p={st.test_equal_odds().pvalue:.2f}")

    data = ct.assign(sps_low=ct["sps_low"].astype(int))
    full = smf.logit("int60 ~ sps_low + C(region) + C(instance_type) + C(period)", data=data).fit(disp=0)
    no_period = smf.logit("int60 ~ sps_low + C(region) + C(instance_type)", data=data).fit(disp=0)
    lr = 2 * (full.llf - no_period.llf)
    print(f"ロジスティック回帰: SPS低下のオッズ比={np.exp(full.params['sps_low']):.2f}")
    print(f"SPS で調整した後の時間帯の効果 (尤度比検定): chi2={lr:.1f}, p={stats.chi2.sf(lr, 3):.1e}")

    n_int = ct["int60"].sum()
    n_int_usual = ct[~ct["sps_low"]]["int60"].sum()
    print(f"\nSPS が通常値のときの中断: {n_int_usual}/{n_int} ({n_int_usual / n_int:.0%})")
    for t in TARGET_TYPES:
        g = ct[ct["instance_type"] == t]
        print(f"  {t}: {g[~g['sps_low']]['int60'].sum()}/{g['int60'].sum()}, "
              f"低下の割合(起動成功のうち)={g['sps_low'].mean():.1%}")

    print("\nSPS 低下を中断の予測として見た場合")
    low = ct[ct["sps_low"]]
    print(f"  SPS 低下時に 60 分間中断されなかった割合: {(low['int60'] == 0).mean():.0%} ({len(low)}件)")

    print("\nSPS が通常値の条件内での F_comp(60) の変動 (リージョン x 時間帯)")
    usual = ct[~ct["sps_low"]]
    for t in TARGET_TYPES:
        g = usual[usual["instance_type"] == t]
        f60 = 1 - g.groupby(["region", "period"])["int60"].mean()
        chi2, p, dof, _ = stats.chi2_contingency(pd.crosstab([g["region"], g["period"]], g["int60"]))
        print(f"  {t}: F60 {f60.min():.2f} -- {f60.max():.2f}, chi2={chi2:.1f}, dof={dof}, p={p:.3f}")

    print("\n表: SPS が通常値のときの時間帯別 F_comp(60)")
    for t in TARGET_TYPES:
        g = usual[usual["instance_type"] == t]
        chi2, p, dof, _ = stats.chi2_contingency(pd.crosstab(g["period"], g["int60"]))
        print(f"  {t} (chi2={chi2:.1f}, dof={dof}, p={p:.4f})")
        for period in PERIODS:
            x = g[g["period"] == period]
            n, k = len(x), int((x["int60"] == 0).sum())
            lo, hi = wilson(k, n)
            print(f"    {period:9s}: F60={k / n:.2f} [{lo:.2f}, {hi:.2f}] (n={n}, 中断={n - k})")


if __name__ == "__main__":
    main()
