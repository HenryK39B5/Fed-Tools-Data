"""
Compute industry-level contributions to total nonfarm payroll gains.

The output is a JSON-friendly payload used by the web front-end to draw
horizontal stacked bars (one row per month, stacked by industry share).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DEFAULT_DB_URL = "sqlite:///./fomc_data.db"

# Ordered list comes from README "分行业新增就业"列表
INDUSTRY_SERIES = [
    ("采矿业", "USMINE"),
    ("建筑业", "USCONS"),
    ("制造业", "MANEMP"),
    ("批发业", "USWTRADE"),
    ("零售业", "USTRADE"),
    ("运输仓储业", "USTPU"),
    ("公用事业", "CES4422000001"),
    ("信息业", "USINFO"),
    ("金融活动", "USFIRE"),
    ("专业和商业服务", "USPBS"),
    ("教育和保健服务", "USEHS"),
    ("休闲和酒店业", "USLAH"),
    ("其他服务业", "USSERV"),
    ("政府", "USGOVT"),
]


@dataclass
class IndustryContributionPayload:
    labels: List[str]
    datasets: List[Dict[str, object]]
    latest_period: Optional[str]
    top_positive: List[Dict[str, object]]
    top_negative: List[Dict[str, object]]


class IndustryContributionChartBuilder:
    """Prepare industry contribution ratios for the most recent 12 months (inclusive)."""

    def __init__(self, database_url: str = DEFAULT_DB_URL):
        self.database_url = database_url
        connect_args: Dict[str, bool] = {}
        if database_url.startswith("sqlite:///"):
            connect_args["check_same_thread"] = False
        self.engine: Engine = create_engine(database_url, connect_args=connect_args, echo=False)

    def prepare_payload(
        self, year: Optional[int] = None, as_of: Optional[datetime] = None
    ) -> IndustryContributionPayload:
        anchor_date = as_of or (datetime(year, 12, 31) if year else datetime.now())
        end_period = pd.Period(anchor_date, freq="M")
        start_period = end_period - 11

        total_df = self._load_indicator_series("PAYEMS")
        total_df["period"] = total_df["date"].dt.to_period("M")
        total_df["monthly_change"] = total_df["value"].diff()
        total_window = total_df[
            (total_df["period"] >= start_period) & (total_df["period"] <= end_period)
        ]

        if total_window.empty:
            raise ValueError(
                f"{start_period.strftime('%Y-%m')} 至 {end_period.strftime('%Y-%m')} 缺少 PAYEMS 数据，无法计算分行业贡献。"
            )

        # Months where total change is non-zero (avoid division by zero)
        total_change = total_window.set_index("period")["monthly_change"]
        valid_periods = [p for p in total_change.index if pd.notna(total_change[p]) and total_change[p] != 0]
        if not valid_periods:
            raise ValueError(
                f"{start_period.strftime('%Y-%m')} 至 {end_period.strftime('%Y-%m')} 缺少可用的新增非农就业数据（增量为0或缺失）。"
            )

        # Preserve chronological order
        valid_periods = sorted(valid_periods)
        labels = [p.strftime("%Y-%m") for p in valid_periods]

        contribution_table = pd.DataFrame(index=valid_periods)
        top_positive: List[Dict[str, object]] = []
        top_negative: List[Dict[str, object]] = []

        for name, code in INDUSTRY_SERIES:
            df = self._load_indicator_series(code)
            df["period"] = df["date"].dt.to_period("M")
            df["monthly_change"] = df["value"].diff()
            df_window = df[(df["period"] >= start_period) & (df["period"] <= end_period)]

            series = df_window.set_index("period")["monthly_change"].reindex(valid_periods)
            contribution_table[code] = (series / total_change.reindex(valid_periods)) * 100

        datasets: List[Dict[str, object]] = []
        for name, code in INDUSTRY_SERIES:
            values = [
                round(val, 2) if pd.notna(val) else None for val in contribution_table[code].tolist()
            ]
            datasets.append({"label": name, "code": code, "data": values})

        # Latest month snapshot for text commentary
        latest_period = labels[-1] if labels else None
        if labels:
            latest_period_period = valid_periods[-1]
            latest_row = contribution_table.loc[latest_period_period]
            pos_sorted = latest_row[latest_row > 0].sort_values(ascending=False).dropna()
            neg_sorted = latest_row[latest_row < 0].sort_values().dropna()

            top_positive = [
                {"label": self._name_from_code(code), "code": code, "value": round(val, 2)}
                for code, val in pos_sorted.head(3).items()
            ]
            top_negative = [
                {"label": self._name_from_code(code), "code": code, "value": round(val, 2)}
                for code, val in neg_sorted.head(3).items()
            ]

        return IndustryContributionPayload(
            labels=labels,
            datasets=datasets,
            latest_period=latest_period,
            top_positive=top_positive,
            top_negative=top_negative,
        )

    def _name_from_code(self, fred_code: str) -> str:
        for name, code in INDUSTRY_SERIES:
            if code == fred_code:
                return name
        return fred_code

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


if __name__ == "__main__":
    builder = IndustryContributionChartBuilder()
    payload = builder.prepare_payload(year=datetime.now().year)
    print(f"Built {len(payload.labels)} months of contribution data for {payload.latest_period}.")
