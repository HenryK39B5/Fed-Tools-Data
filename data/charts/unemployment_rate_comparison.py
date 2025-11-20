"""
Chart generator for U-1~U-6 unemployment rates (current vs previous month).

Outputs a grouped bar chart comparing last month vs this month, and provides
structured data for UI consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager as fm
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_DB_URL = "sqlite:///./fomc_data.db"

CATEGORY_ORDER = [
    ("U-1", "U1RATE"),
    ("U-2", "U2RATE"),
    ("U-3", "UNRATE"),
    ("U-4", "U4RATE"),
    ("U-5", "U5RATE"),
    ("U-6", "U6RATE"),
]


@dataclass
class RateSnapshot:
    label: str
    fred_code: str
    current: Optional[float]
    previous: Optional[float]

    @property
    def mom_delta(self) -> Optional[float]:
        if self.current is None or self.previous is None:
            return None
        return self.current - self.previous


@dataclass
class RateComparisonPayload:
    snapshots: List[RateSnapshot]
    start_period: pd.Period
    end_period: pd.Period


class UnemploymentRateComparisonBuilder:
    """Compute and plot U-1~U-6 grouped bars for the target month."""

    def __init__(self, database_url: str = DEFAULT_DB_URL):
        self.database_url = database_url
        self._configure_fonts()
        connect_args: Dict[str, bool] = {}
        if database_url.startswith("sqlite:///"):
            connect_args["check_same_thread"] = False
        self.engine: Engine = create_engine(database_url, connect_args=connect_args, echo=False)

    def _configure_fonts(self) -> None:
        preferred_fonts = [
            "SimHei",
            "Microsoft YaHei",
            "Noto Sans CJK SC",
            "WenQuanYi Micro Hei",
            "Source Han Sans SC",
        ]
        available_fonts = {font.name for font in fm.fontManager.ttflist}
        for font_name in preferred_fonts:
            if font_name in available_fonts:
                plt.rcParams["font.sans-serif"] = [font_name] + plt.rcParams.get("font.sans-serif", [])
                plt.rcParams["axes.unicode_minus"] = False
                return
        plt.rcParams["axes.unicode_minus"] = False

    def build(
        self, as_of: Optional[datetime] = None
    ) -> Tuple[plt.Figure, RateComparisonPayload]:
        payload = self.prepare_payload(as_of=as_of)
        fig = self._plot(payload)
        return fig, payload

    def prepare_payload(self, as_of: Optional[datetime]) -> RateComparisonPayload:
        """Prepare datasets without plotting."""

        return self._prepare_snapshots(as_of=as_of)

    def _prepare_snapshots(self, as_of: Optional[datetime]) -> RateComparisonPayload:
        all_snapshots: List[RateSnapshot] = []
        target_period = pd.Period(as_of, freq="M") if as_of else None
        # If no as_of is supplied, use the latest shared month across series.
        if target_period is None:
            target_period = self._latest_common_period()

        previous_period = target_period - 1

        for label, code in CATEGORY_ORDER:
            df = self._load_indicator_series(code)
            df["period"] = df["date"].dt.to_period("M")

            current_row = df[df["period"] == target_period]
            prev_row = df[df["period"] == previous_period]

            current_val = float(current_row.iloc[-1]["value"]) if not current_row.empty else None
            prev_val = float(prev_row.iloc[-1]["value"]) if not prev_row.empty else None

            all_snapshots.append(
                RateSnapshot(label=label, fred_code=code, current=current_val, previous=prev_val)
            )

        return RateComparisonPayload(
            snapshots=all_snapshots,
            start_period=previous_period,
            end_period=target_period,
        )

    def _plot(self, payload: RateComparisonPayload) -> plt.Figure:
        labels = [snap.label for snap in payload.snapshots]
        prev_values = [snap.previous for snap in payload.snapshots]
        current_values = [snap.current for snap in payload.snapshots]

        x = range(len(labels))
        width = 0.35

        fig, ax = plt.subplots(figsize=(10, 5.5))
        ax.bar(
            [p - width / 2 for p in x],
            prev_values,
            width=width,
            label=f"{payload.start_period.strftime('%Y-%m')}",
            color="#8da9c4",
        )
        ax.bar(
            [p + width / 2 for p in x],
            current_values,
            width=width,
            label=f"{payload.end_period.strftime('%Y-%m')}",
            color="#2f78c4",
        )

        ax.set_xticks(list(x))
        ax.set_xticklabels(labels)
        ax.set_ylabel("失业率(%)")
        ax.set_title("图2：美国各类型失业率(%)", loc="left", pad=12)
        ax.legend(loc="upper left", bbox_to_anchor=(0, 1.02), ncol=2, frameon=False)
        ax.grid(axis="y", alpha=0.2)

        for idx, val in enumerate(current_values):
            if val is not None:
                ax.text(idx + width / 2, val + 0.05, f"{val:.2f}", ha="center", va="bottom", fontsize=9)
        for idx, val in enumerate(prev_values):
            if val is not None:
                ax.text(idx - width / 2, val + 0.05, f"{val:.2f}", ha="center", va="bottom", fontsize=9, color="#2c3e50")

        fig.tight_layout()
        return fig

    def _load_indicator_series(self, fred_code: str) -> pd.DataFrame:
        query = text(
            """
            SELECT dp.date AS date, dp.value AS value
            FROM economic_data_points AS dp
            INNER JOIN economic_indicators AS ei ON ei.id = dp.indicator_id
            WHERE ei.code = :fred_code
            ORDER BY dp.date ASC
            """
        )
        df = pd.read_sql_query(query, self.engine, params={"fred_code": fred_code}, parse_dates=["date"])
        if df.empty:
            raise ValueError(f"未能在数据库中找到指标 {fred_code} 的数据。")
        return df

    def _latest_common_period(self) -> pd.Period:
        latest_periods = []
        for _, code in CATEGORY_ORDER:
            df = self._load_indicator_series(code)
            max_date = df["date"].max()
            latest_periods.append(max_date.to_period("M"))
        return min(latest_periods)


if __name__ == "__main__":
    builder = UnemploymentRateComparisonBuilder()
    figure, payload = builder.build()
    print(
        f"Chart covers {payload.start_period} vs {payload.end_period}; "
        f"series count: {len(payload.snapshots)}"
    )
    plt.show()
