"""
Chart generator for "新增非农就业（万人）及失业率(%，右)".

The module keeps the chart pipeline decoupled from the rest of the system:
1. Read indicator series (PAYEMS & UNRATE) directly from the project database.
2. Transform PAYEMS into monthly changes expressed in ten-thousand jobs.
3. Plot a combo chart (bars + secondary-axis line) limited to the latest 3 years.

Usage
-----
from data.charts.nonfarm_jobs_chart import LaborMarketChartBuilder

builder = LaborMarketChartBuilder()
figure, payload = builder.build(save_path="charts/nonfarm_vs_unemployment.png")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_DB_URL = "sqlite:///./fomc_data.db"


@dataclass
class ChartPayload:
    """
    Structured bundle describing the transformed datasets that feed the chart.
    """

    payems_changes: pd.DataFrame
    unemployment_rate: pd.DataFrame
    start_date: datetime
    end_date: datetime


class LaborMarketChartBuilder:
    """
    Builder that loads, transforms, and plots the labor-market combo chart.
    """

    def __init__(self, database_url: str = DEFAULT_DB_URL, lookback_years: int = 3):
        self.database_url = database_url
        self.lookback_years = lookback_years
        self._configure_fonts()
        connect_args: Dict[str, bool] = {}
        if database_url.startswith("sqlite:///"):
            # SQLite needs this flag when the engine is shared across threads.
            connect_args["check_same_thread"] = False
        self.engine: Engine = create_engine(database_url, connect_args=connect_args, echo=False)

    def _configure_fonts(self) -> None:
        """
        Ensure matplotlib can render Chinese characters by picking the first available CJK font.
        """

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

        # Fallback: still disable unicode minus to avoid boxes
        plt.rcParams["axes.unicode_minus"] = False

    def build(
        self, save_path: Optional[str] = None, as_of: Optional[datetime] = None
    ) -> Tuple[plt.Figure, ChartPayload]:
        """Public entry point: prepare data, then plot."""

        payload = self.prepare_payload(as_of=as_of)
        fig = self._plot(payload)

        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches="tight")

        return fig, payload

    def prepare_payload(self, as_of: Optional[datetime] = None) -> ChartPayload:
        """Prepare datasets without plotting (for API usage)."""

        return self._prepare_datasets(as_of=as_of)

    def _prepare_datasets(self, as_of: Optional[datetime] = None) -> ChartPayload:
        """
        Load the PAYEMS & UNRATE series, transform them, and constrain to the desired window.
        """

        payems = self._load_indicator_series("PAYEMS")
        payems["monthly_change"] = payems["value"].diff()
        payems["monthly_change_10k"] = payems["monthly_change"] / 10.0
        payems = payems.dropna(subset=["monthly_change_10k"])

        start_date, end_date = self._infer_window(payems, as_of=as_of)
        payems_window = payems[(payems["date"] >= start_date) & (payems["date"] <= end_date)].copy()

        unemployment = self._load_indicator_series("UNRATE")
        unemployment_window = unemployment[
            (unemployment["date"] >= start_date) & (unemployment["date"] <= end_date)
        ].copy()

        return ChartPayload(
            payems_changes=payems_window,
            unemployment_rate=unemployment_window,
            start_date=start_date,
            end_date=end_date,
        )

    def _plot(self, payload: ChartPayload) -> plt.Figure:
        """
        Render the combo chart given prepared datasets.
        """

        fig, ax_left = plt.subplots(figsize=(12, 6))

        # Bar chart: monthly change in PAYEMS (ten-thousand jobs)
        ax_left.bar(
            payload.payems_changes["date"],
            payload.payems_changes["monthly_change_10k"],
            color="#1f77b4",
            alpha=0.8,
            width=20,
            label="新增非农就业（万人）",
        )
        ax_left.axhline(0, color="#666666", linewidth=0.8)
        ax_left.set_ylabel("新增非农就业（万人）")

        # Line chart: unemployment rate (secondary axis)
        ax_right = ax_left.twinx()
        ax_right.plot(
            payload.unemployment_rate["date"],
            payload.unemployment_rate["value"],
            color="#ff7f0e",
            linewidth=2,
            label="失业率(%)",
        )
        ax_right.set_ylabel("失业率(%)")

        ax_left.set_title("图1：新增非农就业（万人）及失业率(%，右)", loc="left", pad=14)
        ax_left.set_xlabel("日期")
        ax_left.set_xlim(payload.start_date, payload.end_date)

        # Improve x-axis readability.
        fig.autofmt_xdate()

        # Build a combined legend.
        handles_left, labels_left = ax_left.get_legend_handles_labels()
        handles_right, labels_right = ax_right.get_legend_handles_labels()
        ax_left.legend(
            handles_left + handles_right,
            labels_left + labels_right,
            loc="upper left",
            bbox_to_anchor=(0, 1.02),
            ncol=2,
            frameon=False,
        )

        fig.tight_layout()
        return fig

    def _load_indicator_series(self, fred_code: str) -> pd.DataFrame:
        """
        Load every data point for the specified FRED series.
        """

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

    def _infer_window(self, df: pd.DataFrame, as_of: Optional[datetime] = None) -> Tuple[datetime, datetime]:
        """
        Given a DataFrame sorted by date, compute the desired lookback window.
        """

        latest_date = df["date"].max()
        end_candidate = latest_date
        if as_of:
            # Ensure the requested month does not exceed available data.
            as_of_ts = pd.Timestamp(as_of)
            end_candidate = min(latest_date, as_of_ts)
        end_date = end_candidate
        start_date = end_date - pd.DateOffset(years=self.lookback_years)
        return start_date.to_pydatetime(), end_date.to_pydatetime()


if __name__ == "__main__":
    builder = LaborMarketChartBuilder()
    figure, payload = builder.build()
    print(
        f"Chart covers {payload.start_date.date()} ~ {payload.end_date.date()} "
        f"({len(payload.payems_changes)} payroll observations, "
        f"{len(payload.unemployment_rate)} unemployment observations)."
    )
    plt.show()
