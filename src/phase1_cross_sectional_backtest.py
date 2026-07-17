"""
第一阶段完整示例：
基于动量、反转、波动率与流动性的横截面 Top-20% 回测。

特点：
1. 无需联网；若未提供 CSV，则自动生成模拟数据。
2. 因子按日期进行横截面去极值与标准化。
3. 信号滞后一天，降低收盘价信息泄露风险。
4. 输出 RankIC、换手率、成本前后收益和累计净值图。

真实 CSV 至少包含：
date,ticker,close,volume
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DATA_PATH = Path("data/prices.csv")
OUTPUT_DIR = Path("outputs")
TOP_FRACTION = 0.20
COST_RATE = 0.001
SEED = 42


def make_demo_panel(
    n_stocks: int = 80,
    n_days: int = 420,
    seed: int = SEED,
) -> pd.DataFrame:
    """生成不依赖网络的模拟股票面板数据。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n_days)
    tickers = [f"S{i:03d}" for i in range(n_stocks)]
    sectors = [f"行业{j}" for j in range(8)]

    market_ret = rng.normal(0.0002, 0.009, size=n_days)
    rows: list[pd.DataFrame] = []

    for i, ticker in enumerate(tickers):
        beta = rng.uniform(0.7, 1.3)
        idiosyncratic_ret = rng.normal(
            0,
            rng.uniform(0.008, 0.018),
            size=n_days,
        )
        stock_ret = beta * market_ret + idiosyncratic_ret

        close = 50 * np.exp(np.cumsum(stock_ret))
        volume = rng.lognormal(
            mean=14.0,
            sigma=0.45,
            size=n_days,
        )

        rows.append(pd.DataFrame({
            "date": dates,
            "ticker": ticker,
            "sector": sectors[i % len(sectors)],
            "close": close,
            "volume": volume,
        }))

    panel = pd.concat(rows, ignore_index=True)
    return panel.sort_values(
        ["ticker", "date"]
    ).reset_index(drop=True)


def load_panel(path: Path) -> pd.DataFrame:
    """读取真实 CSV；文件不存在时使用模拟数据。"""
    if path.exists():
        df = pd.read_csv(path, parse_dates=["date"])
        print(f"读取真实数据：{path}")
    else:
        df = make_demo_panel()
        print("未发现 data/prices.csv，使用模拟数据。")

    return df.sort_values(
        ["ticker", "date"]
    ).reset_index(drop=True)


def audit_panel(df: pd.DataFrame) -> dict:
    """执行最基本的数据完整性检查。"""
    required = {"date", "ticker", "close", "volume"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"缺少字段：{sorted(missing)}")

    if df.duplicated(["date", "ticker"]).any():
        raise ValueError("存在 date-ticker 重复记录。")

    if df[["date", "ticker", "close"]].isna().any().any():
        raise ValueError("关键字段存在缺失值。")

    if (df["close"] <= 0).any():
        raise ValueError("存在非正价格。")

    sorted_ok = (
        df.groupby("ticker")["date"]
        .apply(lambda s: s.is_monotonic_increasing)
        .all()
    )

    if not sorted_ok:
        raise ValueError("股票内部日期顺序异常。")

    return {
        "rows": int(len(df)),
        "stocks": int(df["ticker"].nunique()),
        "trading_days": int(df["date"].nunique()),
        "start_date": str(df["date"].min().date()),
        "end_date": str(df["date"].max().date()),
    }


def cs_winsorize(
    s: pd.Series,
    lower: float = 0.01,
    upper: float = 0.99,
) -> pd.Series:
    """按横截面分位数去极值。"""
    if s.notna().sum() < 5:
        return s

    low, high = s.quantile([lower, upper])
    return s.clip(low, high)


def cs_zscore(s: pd.Series) -> pd.Series:
    """按横截面计算 z-score。"""
    std = s.std(ddof=0)

    if pd.isna(std) or std < 1e-12:
        return pd.Series(np.nan, index=s.index)

    return (s - s.mean()) / std


def build_features(panel: pd.DataFrame) -> pd.DataFrame:
    """构造传统因子、未来收益标签和滞后信号。"""
    df = panel.copy().sort_values(["ticker", "date"])

    df["ret_1d"] = (
        df.groupby("ticker")["close"].pct_change()
    )
    df["mom_20"] = (
        df.groupby("ticker")["close"].pct_change(20)
    )
    df["reversal_5"] = -(
        df.groupby("ticker")["close"].pct_change(5)
    )
    df["vol_20"] = (
        df.groupby("ticker")["ret_1d"]
        .transform(
            lambda s: s.rolling(
                20,
                min_periods=20,
            ).std()
        )
    )
    df["liquidity"] = np.log1p(
        df["close"] * df["volume"]
    )

    # 未来收益只能用于标签和评价。
    df["target_5d"] = (
        df.groupby("ticker")["close"].shift(-5)
        / df["close"]
        - 1
    )
    df["ret_fwd_1d"] = (
        df.groupby("ticker")["close"].shift(-1)
        / df["close"]
        - 1
    )

    raw_features = [
        "mom_20",
        "reversal_5",
        "vol_20",
        "liquidity",
    ]

    for col in raw_features:
        df[f"{col}_w"] = (
            df.groupby("date")[col]
            .transform(cs_winsorize)
        )
        df[f"{col}_z"] = (
            df.groupby("date")[f"{col}_w"]
            .transform(cs_zscore)
        )

    df["factor_score"] = (
        0.50 * df["mom_20_z"]
        + 0.25 * df["reversal_5_z"]
        - 0.20 * df["vol_20_z"]
        + 0.05 * df["liquidity_z"]
    )

    # 因子使用了当日收盘数据，因此组合使用滞后一天的分数。
    df["signal_lag1"] = (
        df.groupby("ticker")["factor_score"].shift(1)
    )

    return df


def one_day_rank_ic(x: pd.DataFrame) -> float:
    """计算单日 Spearman RankIC。"""
    valid = x[
        ["factor_score", "target_5d"]
    ].dropna()

    if (
        len(valid) < 10
        or valid["factor_score"].nunique() < 2
        or valid["target_5d"].nunique() < 2
    ):
        return np.nan

    ranked = valid.rank()
    return float(ranked.corr().iloc[0, 1])


def calculate_rank_ic(df: pd.DataFrame) -> pd.Series:
    """生成按日期排列的 RankIC 序列。"""
    return (
        df.groupby("date")[
            ["factor_score", "target_5d"]
        ]
        .apply(one_day_rank_ic)
        .dropna()
        .rename("rank_ic")
    )


def build_portfolio(
    df: pd.DataFrame,
    top_fraction: float = TOP_FRACTION,
    cost_rate: float = COST_RATE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """构造 Top 分位数等权组合并扣除简化交易成本。"""
    if not 0 < top_fraction < 1:
        raise ValueError("top_fraction 必须位于 (0, 1)。")

    bt = df.dropna(
        subset=["signal_lag1", "ret_fwd_1d"]
    ).copy()

    bt["rank_pct"] = (
        bt.groupby("date")["signal_lag1"]
        .rank(pct=True, method="first")
    )
    bt["selected"] = (
        bt["rank_pct"] >= 1 - top_fraction
    )

    n_selected = (
        bt.groupby("date")["selected"]
        .transform("sum")
    )

    if (n_selected <= 0).any():
        raise RuntimeError("某些日期没有选中任何股票。")

    bt["weight"] = np.where(
        bt["selected"],
        1.0 / n_selected,
        0.0,
    )
    bt["weighted_return"] = (
        bt["weight"] * bt["ret_fwd_1d"]
    )

    gross_return = (
        bt.groupby("date")["weighted_return"]
        .sum()
        .rename("gross_return")
    )
    benchmark_return = (
        bt.groupby("date")["ret_fwd_1d"]
        .mean()
        .rename("benchmark_return")
    )

    weight_matrix = (
        bt.pivot(
            index="date",
            columns="ticker",
            values="weight",
        )
        .fillna(0.0)
        .sort_index()
    )

    turnover = (
        weight_matrix.diff().abs().sum(axis=1) / 2
    )
    turnover.iloc[0] = (
        weight_matrix.iloc[0].abs().sum() / 2
    )
    turnover = turnover.rename("turnover")

    result = pd.concat(
        [gross_return, benchmark_return, turnover],
        axis=1,
    ).dropna()

    result["cost"] = result["turnover"] * cost_rate
    result["net_return"] = (
        result["gross_return"] - result["cost"]
    )
    result["excess_net_return"] = (
        result["net_return"]
        - result["benchmark_return"]
    )

    return result, bt


def performance_metrics(
    returns: pd.Series,
    periods_per_year: int = 252,
) -> dict:
    """计算一组最基本的组合绩效指标。"""
    r = pd.Series(returns).dropna()

    if len(r) == 0:
        raise ValueError("收益序列为空。")

    wealth = (1 + r).cumprod()
    drawdown = wealth / wealth.cummax() - 1
    std = r.std(ddof=1)

    annual_return = (
        wealth.iloc[-1] ** (periods_per_year / len(r))
        - 1
    )
    annual_volatility = std * np.sqrt(periods_per_year)
    sharpe = (
        r.mean() / std * np.sqrt(periods_per_year)
        if std > 1e-12
        else np.nan
    )

    return {
        "sample_days": int(len(r)),
        "annual_return": float(annual_return),
        "annual_volatility": float(annual_volatility),
        "sharpe": float(sharpe),
        "max_drawdown": float(drawdown.min()),
    }


def save_equity_curve(result: pd.DataFrame) -> None:
    """保存策略与基准累计净值图。"""
    wealth = pd.DataFrame(index=result.index)
    wealth["strategy_net"] = (
        1 + result["net_return"]
    ).cumprod()
    wealth["benchmark"] = (
        1 + result["benchmark_return"]
    ).cumprod()

    ax = wealth.plot(
        figsize=(10, 5),
        title="Strategy Net Value vs Benchmark",
    )
    ax.set_xlabel("Date")
    ax.set_ylabel("Net Value")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(
        OUTPUT_DIR / "net_value.png",
        dpi=160,
    )
    plt.close()


def cost_sensitivity(
    result: pd.DataFrame,
    cost_rates: list[float],
) -> pd.DataFrame:
    """输出不同成本率下的绩效变化。"""
    rows = []

    for rate in cost_rates:
        net = (
            result["gross_return"]
            - result["turnover"] * rate
        )
        metrics = performance_metrics(net)
        metrics["cost_rate"] = rate
        rows.append(metrics)

    return pd.DataFrame(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    panel = load_panel(DATA_PATH)
    audit = audit_panel(panel)
    features = build_features(panel)

    feature_cols = [
        "mom_20",
        "reversal_5",
        "vol_20",
        "liquidity",
    ]
    missing_rates = (
        features[feature_cols]
        .isna()
        .mean()
        .rename("missing_rate")
    )

    rank_ic = calculate_rank_ic(features)
    result, positions = build_portfolio(features)

    strategy_metrics = performance_metrics(
        result["net_return"]
    )
    benchmark_metrics = performance_metrics(
        result["benchmark_return"]
    )

    metrics = {
        "audit": audit,
        "rank_ic_mean": float(rank_ic.mean()),
        "rank_ic_std": float(rank_ic.std()),
        "rank_ic_ir_simple": float(
            rank_ic.mean() / rank_ic.std()
        ),
        "average_turnover": float(
            result["turnover"].mean()
        ),
        "strategy_net": strategy_metrics,
        "benchmark": benchmark_metrics,
    }

    sensitivity = cost_sensitivity(
        result,
        [0.0005, 0.0010, 0.0020, 0.0030],
    )

    result.to_csv(
        OUTPUT_DIR / "daily_backtest.csv",
        encoding="utf-8-sig",
    )
    rank_ic.to_csv(
        OUTPUT_DIR / "rank_ic.csv",
        encoding="utf-8-sig",
    )
    missing_rates.to_csv(
        OUTPUT_DIR / "feature_missing_rates.csv",
        encoding="utf-8-sig",
    )
    sensitivity.to_csv(
        OUTPUT_DIR / "cost_sensitivity.csv",
        index=False,
        encoding="utf-8-sig",
    )

    with open(
        OUTPUT_DIR / "metrics.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            metrics,
            f,
            ensure_ascii=False,
            indent=2,
        )

    save_equity_curve(result)

    print("\n=== 数据审计 ===")
    print(json.dumps(audit, ensure_ascii=False, indent=2))

    print("\n=== 因子缺失率 ===")
    print(missing_rates)

    print("\n=== 主要结果 ===")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    print("\n=== 成本敏感性 ===")
    print(sensitivity.to_string(index=False))

    print(f"\n结果已保存至：{OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
