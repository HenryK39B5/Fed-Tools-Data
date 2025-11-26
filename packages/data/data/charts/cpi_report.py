"""
Chart/data helper for CPI-focused report generation.

Responsibilities:
- Load CPI headline与核心（CPIAUCSL、CPILFESL）并计算同比/环比序列。
- 读取 docs/cpi_weights.csv 中的年度分项权重（中文列名），并按报告年份选择最近年份的权重。
- 提供分项（食品、能源、核心商品、核心服务及其子项）的同比/环比“拉动”表格，标记主要大类便于前端加粗。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import os

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_DB_URL = "sqlite:///./fomc_data.db"


# 近似权重（相对重要性%，可根据BLS年度调整）
DEFAULT_WEIGHTS: Dict[str, float] = {}


COMPONENTS = [
    {"label": "食品", "code": "CPIUFDSL", "is_major": True},
    {"label": "家庭食品", "code": "CUSR0000SAF11", "parent": "食品"},
    {"label": "在外饮食", "code": "CUUR0000SEFV", "parent": "食品"},
    {"label": "能源", "code": "CPIENGSL", "is_major": True},
    {"label": "能源商品", "code": "CUSR0000SACE", "parent": "能源"},
    {"label": "燃油和其他燃料", "code": "CUSR0000SEHE", "parent": "能源商品"},
    {"label": "发动机燃料（汽油）", "code": "CUSR0000SETB", "parent": "能源商品"},
    {"label": "能源服务", "code": "CUSR0000SEHF", "parent": "能源"},
    {"label": "电力", "code": "CUSR0000SEHF01", "parent": "能源服务"},
    {"label": "公用管道燃气服务", "code": "CUSR0000SEHF02", "parent": "能源服务"},
    {"label": "核心商品（不含食品和能源类）", "code": "CUSR0000SACL1E", "is_major": True},
    {"label": "服饰", "code": "CPIAPPSL", "parent": "核心商品（不含食品和能源类）"},
    {"label": "新车", "code": "CUSR0000SETA01", "parent": "核心商品（不含食品和能源类）"},
    {"label": "二手汽车和卡车", "code": "CUSR0000SETA02", "parent": "核心商品（不含食品和能源类）"},
    {"label": "机动车部件和设备", "code": "CUSR0000SETC", "parent": "核心商品（不含食品和能源类）"},
    {"label": "医疗用品", "code": "CUSR0000SAM1", "parent": "核心商品（不含食品和能源类）"},
    {"label": "酒精饮料", "code": "CUSR0000SAF116", "parent": "核心商品（不含食品和能源类）"},
    {"label": "核心服务（不含能源）", "code": "CUSR0000SASLE", "is_major": True},
    {"label": "住所", "code": "CUSR0000SAH1", "parent": "核心服务（不含能源）"},
    {"label": "房租", "code": "CUSR0000SEHA", "parent": "住所"},
    {"label": "水、下水道和垃圾回收", "code": "CUSR0000SEHG", "parent": "住所"},
    {"label": "家庭运营", "code": "CUSR0000SAH3", "parent": "住所"},
    {"label": "医疗服务", "code": "CUSR0000SAM2", "parent": "核心服务（不含能源）"},
    {"label": "运输服务", "code": "CUSR0000SAS4", "parent": "核心服务（不含能源）"},
]


@dataclass
class ContributionRow:
    label: str
    code: str
    parent_label: Optional[str]
    weight: Optional[float]
    current: Optional[float]
    previous: Optional[float]
    contribution: Optional[float]
    previous_contribution: Optional[float]
    delta_contribution: Optional[float]
    is_major: bool = True
    level: int = 0


@dataclass
class CpiReportPayload:
    yoy_series: pd.DataFrame
    mom_series: pd.DataFrame
    contributions_yoy: List[ContributionRow]
    contributions_mom: List[ContributionRow]
    start_date: datetime
    end_date: datetime


class CpiReportBuilder:
    """Prepare CPI headline/core trend series and contribution tables."""

    def __init__(
        self,
        database_url: str = DEFAULT_DB_URL,
        lookback_years: int = 3,
        weight_file_path: Optional[str] = None,
    ):
        self.database_url = database_url
        self.lookback_years = lookback_years
        self.weight_file_path = weight_file_path or self._default_weight_path()
        self.weights_by_year: Dict[int, Dict[str, float]] = {}
        self.last_weight_year: Optional[int] = None
        self._label_aliases = {
            "核心商品": "核心商品（不含食品和能源类）",
            "核心服务": "核心服务（不含能源）",
        }
        connect_args: Dict[str, bool] = {}
        if database_url.startswith("sqlite:///"):
            connect_args["check_same_thread"] = False
        self.engine: Engine = create_engine(database_url, connect_args=connect_args, echo=False)

    def prepare_payload(self, as_of: Optional[datetime] = None) -> CpiReportPayload:
        headline = self._load_indicator_series("CPIAUCSL")
        core = self._load_indicator_series("CPILFESL")

        start_date, end_date = self._infer_window(headline, as_of=as_of)

        if as_of is None:
            as_of = end_date
        self._ensure_weights_loaded()

        yoy = self._build_change_series(headline, core, periods=12, labels=("cpi_yoy", "core_yoy"))
        mom = self._build_change_series(headline, core, periods=1, labels=("cpi_mom", "core_mom"))

        mask = (yoy["date"] >= start_date) & (yoy["date"] <= end_date)
        yoy_window = yoy.loc[mask].copy()
        mom_window = mom.loc[(mom["date"] >= start_date) & (mom["date"] <= end_date)].copy()

        contributions_yoy = self._build_contribution_rows(as_of, periods=12)
        contributions_mom = self._build_contribution_rows(as_of, periods=1)

        return CpiReportPayload(
            yoy_series=yoy_window,
            mom_series=mom_window,
            contributions_yoy=contributions_yoy,
            contributions_mom=contributions_mom,
            start_date=start_date,
            end_date=end_date,
        )

    def _build_contribution_rows(self, as_of: Optional[datetime], periods: int) -> List[ContributionRow]:
        if as_of is None:
            as_of = datetime.utcnow()
        target_period = pd.Period(as_of, freq="M")
        prev_period = target_period - 1
        weights = self._get_weights_for_year(as_of.year)

        parent_map = {comp["label"]: comp.get("parent") for comp in COMPONENTS}
        level_cache: Dict[str, int] = {}

        def level_of(label: str) -> int:
            if label in level_cache:
                return level_cache[label]
            parent_label = parent_map.get(label)
            if not parent_label:
                level_cache[label] = 0
                return 0
            lvl = level_of(parent_label) + 1
            level_cache[label] = lvl
            return lvl

        rows: List[ContributionRow] = []
        for comp in COMPONENTS:
            try:
                series = self._load_indicator_series(comp["code"])
            except Exception:
                series = None
            current_change = self._percent_change_at(series, target_period, months=periods) if series is not None else None
            previous_change = self._percent_change_at(series, prev_period, months=periods) if series is not None else None
            norm_label = self._normalize_label(comp["label"])
            weight = weights.get(norm_label)
            if weight is None and norm_label in self._label_aliases:
                weight = weights.get(self._label_aliases[norm_label])
            if weight is None:
                # try alt normalized alias
                alt = self._normalize_label(self._label_aliases.get(norm_label, norm_label))
                weight = weights.get(alt)

            contribution = self._calc_contribution(weight, current_change)
            prev_contribution = self._calc_contribution(weight, previous_change)
            delta = (
                contribution - prev_contribution
                if contribution is not None and prev_contribution is not None
                else None
            )

            rows.append(
                ContributionRow(
                    label=comp["label"],
                    code=comp["code"],
                    parent_label=comp.get("parent"),
                    weight=weight,
                    current=current_change,
                    previous=previous_change,
                    contribution=contribution,
                    previous_contribution=prev_contribution,
                    delta_contribution=delta,
                    is_major=bool(comp.get("is_major")),
                    level=level_of(comp["label"]),
                )
            )

        return rows

    @staticmethod
    def _calc_contribution(weight: Optional[float], change: Optional[float]) -> Optional[float]:
        if weight is None or change is None:
            return None
        return weight * change / 100.0

    def _percent_change_at(self, df: pd.DataFrame, period: pd.Period, months: int) -> Optional[float]:
        """Compute percent change at a given month vs N months ago."""
        if df is None or df.empty:
            return None
        row_now = self._select_month_row(df, period)
        row_ref = self._select_month_row(df, period - months)
        if row_now is None or row_ref is None:
            return None
        prev_val = row_ref["value"]
        if prev_val == 0:
            return None
        return float((row_now["value"] / prev_val - 1.0) * 100)

    def _build_change_series(
        self,
        headline: pd.DataFrame,
        core: pd.DataFrame,
        periods: int,
        labels: Tuple[str, str],
    ) -> pd.DataFrame:
        series_headline = headline.copy()
        series_core = core.copy()
        series_headline[labels[0]] = series_headline["value"].pct_change(periods=periods) * 100
        series_core[labels[1]] = series_core["value"].pct_change(periods=periods) * 100

        merged = pd.merge(series_headline[["date", labels[0]]], series_core[["date", labels[1]]], on="date", how="outer")
        merged = merged.sort_values("date")
        return merged

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

    def _infer_window(self, df: pd.DataFrame, as_of: Optional[datetime] = None) -> Tuple[datetime, datetime]:
        latest_date = df["date"].max()
        end_candidate = latest_date
        if as_of:
            as_of_ts = pd.Timestamp(as_of)
            end_candidate = min(latest_date, as_of_ts)
        end_date = end_candidate
        start_date = end_date - pd.DateOffset(years=self.lookback_years)
        return start_date.to_pydatetime(), end_date.to_pydatetime()

    def _ensure_weights_loaded(self):
        if self.weights_by_year:
            return
        path = self.weight_file_path
        if not path or not os.path.exists(path):
            return
        try:
            df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        except Exception:
            return
        if df.empty or len(df.columns) < 2:
            return
        # Normalize column names
        columns = []
        for idx, col in enumerate(df.columns):
            if idx == 0 and (col is None or str(col).strip() == "" or "Unnamed" in str(col)):
                columns.append("year")
            else:
                columns.append(self._normalize_label(col))
        df.columns = columns
        year_col = columns[0]

        for _, row in df.iterrows():
            year_val = row.get(year_col)
            try:
                year = int(str(year_val).strip())
            except Exception:
                continue
            weights: Dict[str, float] = {}
            for col in df.columns[1:]:
                val = row.get(col)
                if val is None or str(val).strip() == "":
                    continue
                try:
                    weights[self._normalize_label(col)] = float(str(val).strip())
                except Exception:
                    continue
            if weights:
                self.weights_by_year[year] = weights

    def _get_weights_for_year(self, year: int) -> Dict[str, float]:
        if not self.weights_by_year:
            self.last_weight_year = None
            return {}
        years = sorted(self.weights_by_year.keys())
        target = year - 2  # Relative Importance uses t-2
        selected = None
        for y in years:
            if y <= target:
                selected = y
            else:
                break
        if selected is None:
            # fallback to earliest available
            selected = years[0]
        self.last_weight_year = selected
        return self.weights_by_year.get(selected, {})

    @staticmethod
    def _default_weight_path() -> str:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, "docs", "cpi_weights.csv")

    @staticmethod
    def _normalize_label(label: str) -> str:
        text = str(label).strip()
        # unify fullwidth parentheses/space variants
        text = text.replace("（", "(").replace("）", ")")
        text = text.replace("\u3000", " ").strip()
        return text

    @staticmethod
    def _select_month_row(df: pd.DataFrame, period: pd.Period):
        mask = df["date"].dt.to_period("M") == period
        matches = df.loc[mask]
        if matches.empty:
            return None
        return matches.iloc[-1]


__all__ = [
    "CpiReportBuilder",
    "CpiReportPayload",
    "ContributionRow",
    "COMPONENTS",
    "DEFAULT_WEIGHTS",
]
