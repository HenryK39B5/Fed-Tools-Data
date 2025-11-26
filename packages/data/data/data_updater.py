# Utilities for incremental FRED data updates

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Set

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from data.rate_limited_fred_api import RateLimitedFredAPI
from database.models import EconomicDataPoint, EconomicIndicator

DateRange = Tuple[datetime, datetime]


class IndicatorDataUpdater:
    """
    Helper that figures out which date ranges are missing in the database and
    fetches only those slices from FRED.
    """

    def __init__(
        self,
        session: Session,
        requests_per_minute: int = 30,
        default_start_date: str = "2010-01-01",
    ):
        self.session = session
        self.default_start_date = default_start_date
        self.fred_api = RateLimitedFredAPI(
            requests_per_minute=requests_per_minute,
            default_start_date=default_start_date,
        )

    def update_indicator_data(
        self,
        indicator: EconomicIndicator,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        full_refresh: bool = False,
    ) -> int:
        """
        Fetch missing data for the given indicator.

        Args:
            indicator: SQLAlchemy model instance.
            start_date: Optional desired lower bound (YYYY-MM-DD).
            end_date: Optional desired upper bound (YYYY-MM-DD).
            full_refresh: When True, delete existing data points for this indicator
                          before reloading the requested range.

        Returns:
            Number of newly inserted data points.
        """
        fetch_ranges = self._determine_fetch_ranges(
            indicator.id, start_date, end_date, full_refresh
        )

        if not fetch_ranges:
            return 0

        removed = self._remove_existing_duplicates(indicator.id)
        if removed:
            print(f"Removed {removed} duplicate data points for {indicator.code}")

        total_inserted = 0

        for range_start, range_end in fetch_ranges:
            series_data = self.fred_api.get_series(
                indicator.code,
                observation_start=range_start.strftime("%Y-%m-%d"),
                observation_end=range_end.strftime("%Y-%m-%d"),
            )
            df = self.fred_api.series_to_dataframe(series_data)
            if df.empty:
                continue
            # Drop duplicate dates within the fetched slice to avoid accidental double inserts
            df = df.drop_duplicates(subset=["date"])
            # FRED may return observations outside the requested range (e.g., month starts),
            # so clamp to the intended interval before inserting to avoid unique violations.
            df = df[
                (df["date"] >= pd.Timestamp(range_start))
                & (df["date"] <= pd.Timestamp(range_end))
            ]

            new_points = self._build_data_points(
                indicator.id,
                df,
                range_start,
                range_end,
            )

            if not new_points:
                continue

            self.session.bulk_save_objects(new_points)
            total_inserted += len(new_points)

        if total_inserted or full_refresh:
            self.session.commit()

        return total_inserted

    def _build_data_points(
        self,
        indicator_id: int,
        df: pd.DataFrame,
        range_start: datetime,
        range_end: datetime,
    ) -> List[EconomicDataPoint]:
        min_date = range_start
        max_date = range_end
        existing_dates = {
            row[0]
            for row in self.session.query(EconomicDataPoint.date)
            .filter(
                EconomicDataPoint.indicator_id == indicator_id,
                EconomicDataPoint.date >= min_date,
                EconomicDataPoint.date <= max_date,
            )
            .all()
        }

        new_points: List[EconomicDataPoint] = []
        for row in df.itertuples():
            date_value = row.date.to_pydatetime()
            if date_value in existing_dates:
                continue
            new_points.append(
                EconomicDataPoint(
                    indicator_id=indicator_id,
                    date=date_value,
                    value=row.value,
                )
            )

        return new_points

    def _determine_fetch_ranges(
        self,
        indicator_id: int,
        start_date: Optional[str],
        end_date: Optional[str],
        full_refresh: bool,
    ) -> List[DateRange]:
        min_date, max_date = (
            self.session.query(
                func.min(EconomicDataPoint.date),
                func.max(EconomicDataPoint.date),
            )
            .filter(EconomicDataPoint.indicator_id == indicator_id)
            .one()
        )

        default_start = self._parse_date(self.default_start_date)
        requested_start = (
            self._parse_date(start_date)
            if start_date
            else (min_date if min_date else default_start)
        )
        requested_end = (
            self._parse_date(end_date) if end_date else self._default_end_date()
        )

        if requested_start > requested_end:
            return []

        if full_refresh and (min_date or max_date):
            (
                self.session.query(EconomicDataPoint)
                .filter(EconomicDataPoint.indicator_id == indicator_id)
                .delete(synchronize_session=False)
            )
            self.session.flush()
            min_date = None
            max_date = None

        if not min_date:
            return [(requested_start, requested_end)]

        ranges: List[DateRange] = []

        if start_date and requested_start < min_date:
            ranges.append((requested_start, min_date - timedelta(days=1)))

        if requested_end > max_date:
            start_for_new = max_date + timedelta(days=1)
            if start_for_new <= requested_end:
                ranges.append((start_for_new, requested_end))

        return ranges

    @staticmethod
    def _parse_date(value: str) -> datetime:
        return datetime.strptime(value, "%Y-%m-%d")

    @staticmethod
    def _default_end_date() -> datetime:
        return datetime.now() + timedelta(days=1)

    def _remove_existing_duplicates(self, indicator_id: int) -> int:
        """
        Remove duplicated rows (same indicator/date) that may have slipped in previously.
        Returns number of deleted rows.
        """
        rows = (
            self.session.query(EconomicDataPoint.id, EconomicDataPoint.date)
            .filter(EconomicDataPoint.indicator_id == indicator_id)
            .order_by(EconomicDataPoint.date, EconomicDataPoint.id)
            .all()
        )
        seen: Set[datetime] = set()
        duplicates: List[int] = []
        for point_id, date in rows:
            if date in seen:
                duplicates.append(point_id)
            else:
                seen.add(date)

        if not duplicates:
            return 0

        (
            self.session.query(EconomicDataPoint)
            .filter(EconomicDataPoint.id.in_(duplicates))
            .delete(synchronize_session=False)
        )
        self.session.flush()
        return len(duplicates)
