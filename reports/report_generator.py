"""
Prompt builder + orchestrator for DeepSeek economic reports.

The generator separates prompt engineering (how we describe charts/data) from
the actual LLM call, keeping it easy to plug into future workflows or swap the
underlying provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .deepseek_client import DeepSeekClient, DeepSeekConfig


@dataclass
class IndicatorSummary:
    """
    Structured representation of a single data point we want the LLM to cover.
    """

    name: str
    latest_value: str
    units: str
    mom_change: Optional[str] = None
    yoy_change: Optional[str] = None
    context: Optional[str] = None

    def as_prompt_line(self) -> str:
        deltas: List[str] = []
        if self.mom_change:
            deltas.append(f"环比: {self.mom_change}")
        if self.yoy_change:
            deltas.append(f"同比: {self.yoy_change}")

        delta_text = f" ({', '.join(deltas)})" if deltas else ""
        context_text = f" | 说明: {self.context}" if self.context else ""
        return f"- {self.name}: {self.latest_value}{self.units}{delta_text}{context_text}"


@dataclass
class ReportFocus:
    """
    Items that guide the narrative emphasis.
    """

    fomc_implications: Sequence[str] = field(default_factory=list)
    risks_to_watch: Sequence[str] = field(default_factory=list)
    market_reaction: Sequence[str] = field(default_factory=list)

    def format_section(self, title: str, items: Sequence[str]) -> str:
        if not items:
            return ""
        formatted_items = "\n".join(f"- {item}" for item in items)
        return f"{title}:\n{formatted_items}\n"

    def as_prompt_block(self) -> str:
        blocks = [
            self.format_section("FOMC考量", self.fomc_implications),
            self.format_section("需要警惕的风险", self.risks_to_watch),
            self.format_section("市场价格表现", self.market_reaction),
        ]
        return "\n".join(filter(None, blocks)).strip()


class EconomicReportGenerator:
    """
    Construct prompts for specific report types and call DeepSeek.
    """

    def __init__(self, client: Optional[DeepSeekClient] = None, config: Optional[DeepSeekConfig] = None):
        self.client = client or DeepSeekClient(config=config)

    def generate_nonfarm_report(
        self,
        report_month: str,
        headline_summary: str,
        labor_market_metrics: Sequence[IndicatorSummary],
        policy_focus: Optional[ReportFocus] = None,
        chart_commentary: Optional[str] = None,
        tone: str = "专业严谨，突出数据结论后再解释逻辑，最后点评FOMC倾向。",
    ) -> str:
        """
        Generate a FOMC-style commentary around nonfarm payroll data.
        """

        prompt = self._build_nonfarm_prompt(
            report_month=report_month,
            headline_summary=headline_summary,
            labor_market_metrics=labor_market_metrics,
            policy_focus=policy_focus,
            chart_commentary=chart_commentary,
            tone=tone,
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是美联储研究部门的宏观经济学家，需要撰写结构化的美国劳动力市场点评。"
                    "严禁编造或猜测未提供的数据；只能引用输入中明确给出的字段、指标或结论。"
                    "若某数据缺失，请直接写明“数据未提供/未传入”，不要创造数值或行业分项。"
                ),
            },
            {"role": "user", "content": prompt},
        ]

        return self.client.generate(messages)

    def _build_nonfarm_prompt(
        self,
        report_month: str,
        headline_summary: str,
        labor_market_metrics: Sequence[IndicatorSummary],
        policy_focus: Optional[ReportFocus],
        chart_commentary: Optional[str],
        tone: str,
    ) -> str:
        metrics_block = "\n".join(metric.as_prompt_line() for metric in labor_market_metrics)
        focus_block = policy_focus.as_prompt_block() if policy_focus else ""
        chart_block = f"图表洞见:\n{chart_commentary}\n" if chart_commentary else ""

        sections = [
            f"报告月份: {report_month}",
            f"核心结论: {headline_summary}",
            "劳动力市场关键数据:",
            metrics_block,
            chart_block,
            focus_block,
            f"写作语气: {tone}",
            (
                "可用数据范围：仅包含已给出的劳动力市场关键数据与图表摘要，"
                "无分行业就业或其他额外指标，若需要引用缺失字段须明确标注“数据未提供”。"
            ),
            (
                "输出要求: 使用Markdown结构化输出，保持“图N｜小标题”风格（券商风格但含“图N”方便定位），顺序如下："
                "\n## 核心结论（简洁列点）；"
                "\n## 图1｜自拟小标题（新增非农就业与失业率，针对图1的数据进行分析，仅引用已提供数据）；"
                "\n## 图2｜自拟小标题（各类型失业率，针对图2的数据进行分析，仅引用已提供数据）；"
                "\n## 图3｜自拟小标题（就业率与劳动参与率，针对图3的数据进行分析，仅引用已提供数据）；"
                "\n## 风险提示（2-3条，仅基于已提供数据或常识性宏观风险，禁止编造数值）。"
                "段落中不得虚构任何未提供的数值或行业分项。"
            ),
            (
                "末尾追加“风险提示”小节，列出2-3条潜在风险，并仅基于已提供数据或常识性宏观风险，禁止编造具体数值。"
            ),
        ]

        return "\n".join(section for section in sections if section).strip()
