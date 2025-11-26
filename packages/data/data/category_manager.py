# Category hierarchy and indicator ordering helpers

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from database.models import IndicatorCategory, EconomicIndicator


@dataclass
class CategoryNode:
    name: str
    sort_order: int
    children: List["CategoryNode"] = field(default_factory=list)


CATEGORY_STRUCTURE: List[CategoryNode] = [
    CategoryNode(
        name="非农就业",
        sort_order=1,
        children=[
            CategoryNode(name="分部门新增就业", sort_order=1),
            CategoryNode(name="季调各类型失业率", sort_order=2),
        ],
    ),
    CategoryNode(
        name="CPI",
        sort_order=2,
        children=[
            CategoryNode(
                name="分项CPI",
                sort_order=1,
                children=[
                    CategoryNode(name="食品类", sort_order=1),
                    CategoryNode(name="能源类", sort_order=2),
                    CategoryNode(name="核心商品类", sort_order=3),
                    CategoryNode(name="核心服务类", sort_order=4),
                ],
            )
        ],
    ),
]

INDICATOR_ORDER: Dict[str, List[str]] = {
    "非农就业": ["非农就业总数", "U-3", "劳动参与率", "就业率"],
    "分部门新增就业": [
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
    ],
    "季调各类型失业率": ["U-1", "U-2", "U-4", "U-5", "U-6"],
    "CPI": ["CPI（季调后）", "核心 CPI"],
    "食品类": ["食品", "家庭食品", "在外饮食"],
    "能源类": [
        "能源",
        "能源商品",
        "燃油和其他燃料",
        "发动机燃料（汽油）",
        "能源服务",
        "电力",
        "公用管道燃气服务",
    ],
    "核心商品类": [
        "核心商品（不含食品和能源类）",
        "家具和其他家用产品",
        "服饰",
        "交通工具（不含汽车燃料）",
        "新车",
        "二手汽车和卡车",
        "机动车部件和设备",
        "医疗用品",
        "酒精饮料",
    ],
    "核心服务类": [
        "核心服务（不含能源）",
        "住所",
        "房租",
        "水、下水道和垃圾回收",
        "家庭运营",
        "医疗服务",
        "运输服务",
    ],
}


class CategoryManager:
    """
    Provides a centralized location to enforce hierarchy and ordering rules
    for indicator categories and indicators.
    """

    def __init__(self, session: Session):
        self.session = session

    def ensure_hierarchy(self):
        """
        Make sure required categories and subcategories exist with correct structure.
        """
        for node in CATEGORY_STRUCTURE:
            self._ensure_category(node, parent=None, level=1)
        self.session.commit()

    def apply_indicator_ordering(self):
        """
        Update indicator sort order and category assignments according to INDICATOR_ORDER.
        """
        indicator_map: Dict[str, EconomicIndicator] = {
            indicator.name: indicator for indicator in self.session.query(EconomicIndicator).all()
        }
        category_map: Dict[str, IndicatorCategory] = {
            category.name: category for category in self.session.query(IndicatorCategory).all()
        }

        updated = False
        for category_name, indicator_names in INDICATOR_ORDER.items():
            category = category_map.get(category_name)
            category_id = category.id if category else None

            for index, indicator_name in enumerate(indicator_names, 1):
                indicator = indicator_map.get(indicator_name)
                if not indicator:
                    continue

                indicator_changed = False
                if indicator.sort_order != index:
                    indicator.sort_order = index
                    indicator_changed = True

                if category_id and indicator.category_id != category_id:
                    indicator.category_id = category_id
                    indicator_changed = True

                if indicator_changed:
                    self.session.add(indicator)
                    updated = True

        if updated:
            self.session.commit()

    def _ensure_category(self, node: CategoryNode, parent: Optional[IndicatorCategory], level: int):
        category = self.session.query(IndicatorCategory).filter_by(name=node.name).first()
        if not category:
            category = IndicatorCategory(
                name=node.name,
                level=level,
                parent_id=parent.id if parent else None,
                sort_order=node.sort_order,
            )
            self.session.add(category)
            self.session.flush()
        else:
            changed = False
            if category.sort_order != node.sort_order:
                category.sort_order = node.sort_order
                changed = True
            expected_parent_id = parent.id if parent else None
            if category.parent_id != expected_parent_id:
                category.parent_id = expected_parent_id
                changed = True
            if category.level != level:
                category.level = level
                changed = True
            if changed:
                self.session.add(category)

        for child_node in node.children:
            self._ensure_category(child_node, category, level + 1)
