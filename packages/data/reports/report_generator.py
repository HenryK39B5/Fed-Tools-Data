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

    def generate_cpi_report(
        self,
        report_month: str,
        headline_summary: str,
        inflation_metrics: Sequence[IndicatorSummary],
        contributions_text_yoy: str = "",
        contributions_text_mom: str = "",
        chart_commentary: Optional[str] = None,
        tone: str = "强调数据定量支撑，客观描述驱动项与FOMC关切。",
    ) -> str:
        """Generate CPI-themed narrative."""

        prompt = self._build_cpi_prompt(
            report_month=report_month,
            headline_summary=headline_summary,
            inflation_metrics=inflation_metrics,
            contributions_text_yoy=contributions_text_yoy,
            contributions_text_mom=contributions_text_mom,
            chart_commentary=chart_commentary,
            tone=tone,
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是美联储研究部门的通胀分析师。只使用输入中提供的数据，不得编造或猜测缺失的数值、分项或权重。"
                    "若某分项数据缺失，请明确指出“数据未提供”，不要自行补全。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        return self.client.generate(messages)

    def _build_cpi_prompt(
        self,
        report_month: str,
        headline_summary: str,
        inflation_metrics: Sequence[IndicatorSummary],
        contributions_text_yoy: str,
        contributions_text_mom: str,
        chart_commentary: Optional[str],
        tone: str,
    ) -> str:
        metrics_block = "\n".join(metric.as_prompt_line() for metric in inflation_metrics)
        table_guidance = (
            "表格分析要求：不得输出Markdown表格，仅用1-2段文字解读已提供的拉动列表。"
            "同比表需指出本月/上月权重、主要拉动/拖累项及变化方向；"
            "环比表需突出季调后的价格波动与当月拉动变化。"
        )
        logic_hints = (
            "写作逻辑参考券商CPI点评：先给结论，再拆驱动，再谈粘性与展望。"
            "注意住房服务、能源、食品分项的方向与权重，指出核心服务/核心商品对总 CPI 的拉动或缓和。"
        )
        sections = [
            f"报告月份: {report_month}",
            f"核心结论: {headline_summary}",
            "关键通胀指标:",
            metrics_block,
            "同比拉动拆分:",
            contributions_text_yoy or "未提供同比拆分。",
            "季调环比拆分:",
            contributions_text_mom or "未提供环比拆分。",
            f"图表摘要:\n{chart_commentary}\n" if chart_commentary else "",
            table_guidance,
            logic_hints,
            f"写作语气: {tone}",
            (
                "输出要求：Markdown。章节标题需以“图N｜/表N｜”开头方便定位，小标题内容仅写本节结论，无需再附“定位”文字。顺序："
                "\n## 核心结论（3-5条，覆盖CPI与核心同比/环比、主要拉动力量及变化）；"
                "\n## 图1｜自拟简短结论（内容聚焦：CPI与核心CPI同比；结合最近三年走势与当前值，不要猜测缺失月份）；"
                "\n## 图2｜自拟简短结论（内容聚焦：CPI与核心CPI季调环比；强调当前方向及与上月对比）；"
                "\n## 表1｜自拟简短结论（内容聚焦：CPI同比拉动拆分；先用文字解读提供的拉动列表，点出上月与本月的差异，禁止输出Markdown表格）；"
                "\n## 表2｜自拟简短结论（内容聚焦：季调环比拆分；先用文字解读环比拉动列表，禁止输出Markdown表格）；"
                "\n## 风险提示（2-3条，围绕能源波动、住房服务粘性等常识风险，但不要虚构数值）。"
                "严禁编造市场表现或未提供的数据。"
            ),
        ]
        return "\n".join(s for s in sections if s).strip()

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
                "可用数据范围：包含已给出的劳动力市场关键数据、图表摘要，以及当年分行业新增就业贡献率；"
                "不得猜测市场预期、美元指数、美债、美股或未提供的细分行业/族裔/时薪/工时/JOLTS数据。"
            ),
            (
                "输出要求: 使用Markdown结构化输出，保持“图N｜小标题”风格（券商风格但含“图N”方便定位），顺序如下："
                "\n## 核心结论（列出3-5条，覆盖：非农总量与环比、行业贡献的拉动/拖累、失业率结构、就业率/参与率）；"
                "\n## 图1｜自拟小标题（新增非农就业与失业率，结合环比/均值对比，引用已提供数据）；"
                "\n## 图2｜自拟小标题（分行业新增非农就业贡献率，点出当月拉动与拖累的前几位行业，引用已提供数据）；"
                "\n## 图3｜自拟小标题（各类型失业率，描述U系列的结构差异与环比变化，引用已提供数据）；"
                "\n## 图4｜自拟小标题（就业率与劳动参与率，强调方向与趋势，引用已提供数据）；"
                "\n## 风险提示（2-3条，仅基于已提供数据或常识性宏观风险，禁止编造数值）。"
                "保持简明，但每节给出1-3句具体发现；不得虚构任何未提供的数值或市场反应。"
            ),
            (
                "末尾追加“风险提示”小节，列出2-3条潜在风险，并仅基于已提供数据或常识性宏观风险，禁止编造具体数值。"
            ),
        ]

        return "\n".join(section for section in sections if section).strip()
