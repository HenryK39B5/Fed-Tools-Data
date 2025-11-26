"""Orchestrates indicator metadata + data synchronization from the Excel definition."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from data.category_manager import CategoryManager
from data.data_updater import IndicatorDataUpdater
from database.models import EconomicIndicator, IndicatorCategory


class IndicatorSyncPipeline:
    """
    Central place to keep database sync logic together:
    - Reads the Excel definition
    - Ensures categories/indicators exist
    - Fetches missing data incrementally
    """

    def __init__(
        self,
        session: Session,
        excel_path: str,
        requests_per_minute: int = 30,
        default_start_date: str = "2010-01-01",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        full_refresh: bool = False,
    ):
        self.session = session
        self.excel_path = excel_path
        self.start_date = start_date
        self.end_date = end_date
        self.full_refresh = full_refresh
        self.data_updater = IndicatorDataUpdater(
            session,
            requests_per_minute=requests_per_minute,
            default_start_date=default_start_date,
        )
        self.fred_api = self.data_updater.fred_api
        self.category_manager = CategoryManager(session)
        self.current_subcategories: Dict[str, IndicatorCategory] = {}

    def run(self):
        """Execute metadata + data sync."""
        df = self._load_excel()
        if df is None:
            return

        self.category_manager.ensure_hierarchy()

        try:
            for index, row in df.iterrows():
                board_name = row["板块"]
                indicator_name = row["经济指标"]
                english_name = row["Indicator"]
                fred_code = self._clean_code(row["FRED 代码"])

                print(f"\nProcessing row {index+1}: {board_name} - {indicator_name} ({fred_code})")

                # Category-only rows
                if not fred_code or fred_code == indicator_name:
                    self._record_subcategory(board_name, indicator_name)
                    continue

                # Skip duplicate codes that follow immediately (Excel often repeats)
                if self._is_duplicate_code(df, index, fred_code):
                    print(f"Skipping duplicate row for {indicator_name} ({fred_code})")
                    continue

                board_category = self._get_or_create_category(board_name, level=1, parent_id=None)
                category_id = self._resolve_category_for_indicator(
                    board_name, indicator_name, board_category.id
                )

                indicator = self.session.query(EconomicIndicator).filter_by(code=fred_code).first()

                if not indicator:
                    indicator = self._create_indicator(
                        indicator_name, english_name, fred_code, category_id
                    )
                else:
                    self._update_indicator_if_needed(
                        indicator, indicator_name, english_name, category_id
                    )

                try:
                    inserted = self.data_updater.update_indicator_data(
                        indicator,
                        start_date=self.start_date,
                        end_date=self.end_date,
                        full_refresh=self.full_refresh,
                    )
                    print(f"Stored {inserted} new data points for {indicator_name} ({fred_code})")
                except Exception as e:
                    print(f"Error fetching data for {fred_code}: {str(e)}")
                    self.session.rollback()

            self.category_manager.apply_indicator_ordering()
            print("\nSuccessfully processed all indicators from Excel file")
        except Exception as e:
            print(f"Error processing Excel file: {str(e)}")
            self.session.rollback()

    def _load_excel(self) -> Optional[pd.DataFrame]:
        if not os.path.exists(self.excel_path):
            print(f"Excel file not found at {self.excel_path}")
            return None

        df = pd.read_excel(self.excel_path, sheet_name="Sheet1")
        print(f"Total rows in Excel file: {len(df)}")

        df = df.replace("", pd.NA)
        df["板块"] = df["板块"].ffill()
        df["FRED 代码"] = df["FRED 代码"].ffill()
        df = df.dropna(subset=["板块", "经济指标"], how="all")

        print(f"Total rows after processing: {len(df)}")
        print("First few rows:")
        print(df.head(10))
        return df

    def _clean_code(self, code: object) -> str:
        fred_code = str(code).strip()
        return fred_code.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")

    def _is_duplicate_code(self, df: pd.DataFrame, index: int, fred_code: str) -> bool:
        if index == 0:
            return False
        previous_code = self._clean_code(df.iloc[index - 1]["FRED 代码"])
        return previous_code == fred_code

    def _record_subcategory(self, board_name: str, indicator_name: str):
        """Track current subcategory marker for subsequent indicators."""
        if indicator_name in ["分部门新增就业", "分项 CPI", "季调各类型失业率"]:
            board_category = self._get_or_create_category(board_name, level=1, parent_id=None)
            subcategory = self._get_or_create_category(
                indicator_name, level=2, parent_id=board_category.id
            )
            self.current_subcategories[board_name] = subcategory

    def _get_or_create_category(self, name: str, level: int, parent_id: Optional[int]) -> IndicatorCategory:
        category = self.session.query(IndicatorCategory).filter_by(name=name).first()
        if category:
            if category.level != level or category.parent_id != parent_id:
                category.level = level
                category.parent_id = parent_id
                self.session.commit()
            return category

        category = IndicatorCategory(name=name, level=level, parent_id=parent_id)
        self.session.add(category)
        self.session.commit()
        print(f"Created category: {name} (level {level})")
        return category

    def _resolve_category_for_indicator(
        self, board_name: str, indicator_name: str, board_category_id: int
    ) -> int:
        category_id = board_category_id
        if board_name in self.current_subcategories:
            subcategory_name = self.current_subcategories[board_name].name
            if subcategory_name == "分部门新增就业" and indicator_name in [
                "采矿业",
                "建筑业",
                "制造业",
                "批发业",
                "零售业",
                "运输仓储业",
                "公用事业",
                "信息业",
                "金融活动",
                "专业和商业服务",
                "教育和保健服务",
                "休闲和酒店业",
                "其他服务业",
                "政府",
            ]:
                category_id = self.current_subcategories[board_name].id
            elif subcategory_name == "分项 CPI" and indicator_name in [
                "食品",
                "家庭食品",
                "在外饮食",
                "能源",
                "能源商品",
                "燃油和其他燃料",
                "发动机燃料（汽油）",
                "能源服务",
                "电力",
                "公用管道燃气服务",
                "核心商品（不含食品和能源类）",
                "家具和其他家用产品",
                "服饰",
                "交通工具（不含汽车燃料）",
                "新车",
                "二手汽车和卡车",
                "机动车部件和设备",
                "医疗用品",
                "酒精饮料",
                "核心服务（不含能源）",
                "住所",
                "房租",
                "水、下水道和垃圾回收",
                "家庭运营",
                "医疗服务",
                "运输服务",
            ]:
                category_id = self.current_subcategories[board_name].id
            elif subcategory_name == "季调各类型失业率" and indicator_name in [
                "U-1",
                "U-2",
                "U-3",
                "U-4",
                "U-5",
                "U-6",
            ]:
                category_id = self.current_subcategories[board_name].id
        return category_id

    def _create_indicator(
        self, indicator_name: str, english_name: str, fred_code: str, category_id: int
    ) -> EconomicIndicator:
        try:
            metadata = self.fred_api.get_series_info(fred_code)
            series_info = metadata.get("seriess", [{}])[0]
            description = series_info.get("description", "")
            frequency = series_info.get("frequency", "")
            units = series_info.get("units", "")
            seasonal_adjustment = series_info.get("seasonal_adjustment", "")
            last_updated = series_info.get("last_updated", None)
            if last_updated:
                last_updated = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"Warning: Could not fetch metadata for {fred_code}: {str(e)}")
            description = english_name if english_name else indicator_name
            frequency = ""
            units = ""
            seasonal_adjustment = ""
            last_updated = None

        indicator = EconomicIndicator(
            name=indicator_name,
            code=fred_code,
            english_name=english_name,
            description=description,
            frequency=frequency,
            units=units,
            seasonal_adjustment=seasonal_adjustment,
            last_updated=last_updated,
            category_id=category_id,
        )

        self.session.add(indicator)
        self.session.commit()
        print(f"Created indicator: {indicator_name} ({fred_code})")
        return indicator

    def _update_indicator_if_needed(
        self, indicator: EconomicIndicator, indicator_name: str, english_name: str, category_id: int
    ):
        if (
            indicator.name != indicator_name
            or indicator.english_name != english_name
            or indicator.category_id != category_id
        ):
            indicator.name = indicator_name
            indicator.english_name = english_name
            indicator.category_id = category_id
            self.session.commit()
            print(f"Updated indicator: {indicator_name} ({indicator.code})")
