import base64
import io
import os
import sys
from calendar import monthrange
from datetime import datetime, timedelta, timezone
import json
import html
import re
from bs4 import BeautifulSoup

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from flask import Flask, render_template, jsonify, request, make_response, Response
from dotenv import load_dotenv

# 将项目根目录添加到Python路径中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

# 加载环境变量，供FRED/DeepSeek等服务使用
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# 使用项目根目录的数据库文件
DATABASE_URL = "sqlite:///" + os.path.join(PROJECT_ROOT, "fomc_data.db")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import EconomicIndicator, EconomicDataPoint, IndicatorCategory
from sqlalchemy import func

from data.charts.nonfarm_jobs_chart import LaborMarketChartBuilder
from data.charts.industry_job_contributions import IndustryContributionChartBuilder
from data.charts.unemployment_rate_comparison import UnemploymentRateComparisonBuilder
from reports.report_generator import EconomicReportGenerator, IndicatorSummary, ReportFocus

# 创建引擎和会话
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

app = Flask(__name__, template_folder='templates')

def get_labor_chart_builder():
    """Singleton accessor so we reuse the same chart builder."""
    if not hasattr(app, "_labor_chart_builder"):
        app._labor_chart_builder = LaborMarketChartBuilder(database_url=DATABASE_URL)
    return app._labor_chart_builder


def get_unemployment_chart_builder():
    """Singleton accessor for U-1~U-6 chart builder."""
    if not hasattr(app, "_unemployment_chart_builder"):
        app._unemployment_chart_builder = UnemploymentRateComparisonBuilder(database_url=DATABASE_URL)
    return app._unemployment_chart_builder


def get_industry_contribution_builder():
    """Singleton accessor for industry contribution ratios."""
    if not hasattr(app, "_industry_contribution_builder"):
        app._industry_contribution_builder = IndustryContributionChartBuilder(database_url=DATABASE_URL)
    return app._industry_contribution_builder

def build_economic_report():
    """Lazy init the EconomicReportGenerator, only when API key is configured."""
    if not hasattr(app, "_economic_report_generator"):
        app._economic_report_generator = EconomicReportGenerator()
    return app._economic_report_generator

def get_db_session():
    """获取数据库会话"""
    return SessionLocal()

def parse_report_month(month_text: str):
    """Parse YYYY-MM string to the given month's last day."""
    try:
        base_date = datetime.strptime(month_text, "%Y-%m")
    except (TypeError, ValueError):
        return None
    last_day = monthrange(base_date.year, base_date.month)[1]
    return datetime(base_date.year, base_date.month, last_day)

def figure_to_base64(fig):
    """Convert matplotlib figure to base64 to send via API."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=200, bbox_inches="tight")
    buffer.seek(0)
    encoded = base64.b64encode(buffer.read()).decode("utf-8")
    plt.close(fig)
    return encoded

def select_month_row(df: pd.DataFrame, period: pd.Period):
    """Select dataframe row that matches a specific month period."""
    if df.empty:
        return None
    mask = df["date"].dt.to_period("M") == period
    matches = df.loc[mask]
    if matches.empty:
        return None
    return matches.iloc[-1]

def format_delta(current, reference, decimals: int = 1):
    """Format signed delta values."""
    if current is None or reference is None:
        return None
    delta = current - reference
    return f"{delta:+.{decimals}f}"


def simple_markdown_to_html(md_text: str) -> str:
    """Lightweight Markdown renderer used for PDF export (headings, lists, bold/italic)."""
    if not md_text:
        return ""
    # 去掉可能出现的 ```markdown ... ``` 或 ``` 包裹
    stripped = md_text.strip()
    if stripped.startswith("```"):
        parts = stripped.splitlines()
        # 跳过第一行 fence，去掉最后一行 fence
        if parts:
            parts = parts[1:] if parts[0].startswith("```") else parts
        if parts and parts[-1].startswith("```"):
            parts = parts[:-1]
        stripped = "\n".join(parts)

    lines = stripped.splitlines()
    html_parts = []
    list_buffer = []
    list_type = None  # "ul" or "ol"

    def flush_list():
        nonlocal list_buffer, list_type
        if not list_buffer:
            return
        tag = "ol" if list_type == "ol" else "ul"
        items = "".join(f"<li>{item}</li>" for item in list_buffer)
        html_parts.append(f"<{tag}>{items}</{tag}>")
        list_buffer = []
        list_type = None

    def fmt_inline(text: str) -> str:
        escaped = html.escape(text)
        escaped = escaped.replace("**", "\0").replace("*", "\1")
        escaped = escaped.replace("\0", "<strong>", 1).replace("\0", "</strong>", 1)
        escaped = escaped.replace("\1", "<em>", 1).replace("\1", "</em>", 1)
        return escaped

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_list()
            continue
        if line.startswith("#"):
            flush_list()
            hashes, _, content = line.partition(" ")
            level = min(len(hashes), 3)
            html_parts.append(f"<h{level}>{fmt_inline(content)}</h{level}>")
            continue
        if line.startswith(("-", "*", "+")) and len(line) > 1 and line[1] == " ":
            if list_type not in (None, "ul"):
                flush_list()
            list_type = "ul"
            list_buffer.append(fmt_inline(line[2:].strip()))
            continue
        if line[:1].isdigit() and ". " in line:
            if list_type not in (None, "ol"):
                flush_list()
            list_type = "ol"
            _, _, rest = line.partition(" ")
            list_buffer.append(fmt_inline(rest.strip()))
            continue
        flush_list()
        html_parts.append(f"<p>{fmt_inline(line)}</p>")

    flush_list()
    return "\n".join(html_parts)


def inject_figures_into_report_html(report_html: str, charts: dict) -> str:
    """Insert charts after corresponding heading/paragraph (text before image)."""
    soup = BeautifulSoup(report_html or "", "html.parser")
    body = soup.body or soup

    def make_fig(idx: int, b64: str, title: str):
        fig = soup.new_tag("figure", **{"class": "inline-figure"})
        cap = soup.new_tag("figcaption")
        cap.string = title
        img = soup.new_tag("img", src=f"data:image/png;base64,{b64}", **{"class": "chart", "alt": f'图{idx}'})
        fig.append(cap)
        fig.append(img)
        return fig

    titles = {
        1: "图1：新增非农就业（万人）及失业率(%，右)",
        2: "图2：分行业新增非农就业贡献率(%)",
        3: "图3：各类型失业率(%)",
        4: "图4：就业率和劳动参与率(%)",
    }

    def insert_after_anchor(label: str, fig_tag):
        # find heading containing label
        heading = None
        for h in body.find_all(["h1", "h2", "h3"]):
            if h.get_text(strip=True).find(label) != -1:
                heading = h
                break
        if heading:
            # place after the next block element (p/list/heading following)
            node = heading
            while node and node.next_sibling:
                node = node.next_sibling
                if getattr(node, "name", None) in ["h1", "h2", "h3", "p", "ul", "ol"]:
                    node.insert_after(fig_tag)
                    return True
        # fallback: append to body
        body.append(fig_tag)
        return False

    for idx in range(1, 5):
        key = f"chart{idx}"
        b64 = charts.get(key)
        if not b64:
            continue
        fig_tag = make_fig(idx, b64, titles.get(idx, f"图{idx}"))
        insert_after_anchor(f"图{idx}", fig_tag)

    return str(soup)


def build_pdf_charts(report_payload: dict):
    """Render chart images (base64) for PDF using matplotlib to avoid front-end dependencies."""
    plt.rcParams.update({
        "font.family": ["Times New Roman", "KaiTi", "STKaiti", "DejaVu Serif"],
        "axes.unicode_minus": False,
    })
    figures = {}

    # 图1：PAYEMS + UNRATE
    try:
        payems_series = report_payload.get("payems_series") or []
        unemp_series = report_payload.get("unemployment_series") or []
        labels = [p.get("date") for p in payems_series]
        payems_values = [p.get("monthly_change_10k") or p.get("value") for p in payems_series]
        un_map = {u.get("date"): u.get("value") for u in unemp_series}
        un_values = [un_map.get(d) for d in labels]

        fig, ax1 = plt.subplots(figsize=(7.5, 4))
        ax1.bar(labels, payems_values, color="#2f78c4", alpha=0.75, label="新增非农就业（万人）")
        ax1.set_ylabel("万人")
        ax1.tick_params(axis="x", rotation=45)

        ax2 = ax1.twinx()
        ax2.plot(labels, un_values, color="#ff7f0e", marker="o", linewidth=1.8, label="失业率(%)")
        ax2.set_ylabel("%")

        ax1.legend(loc="upper left")
        ax2.legend(loc="upper right")
        fig.tight_layout()
        figures["chart1"] = figure_to_base64(fig)
    except Exception:
        figures["chart1"] = None

    # 图2：行业贡献率堆叠条形图
    try:
        contrib = report_payload.get("industry_contribution") or {}
        labels = list(reversed(contrib.get("labels") or []))
        datasets = contrib.get("datasets") or []
        fig, ax = plt.subplots(figsize=(7.5, 4))
        current = [0] * len(labels)
        palette = [
            "#1f77b4", "#52b788", "#f4a261", "#e63946", "#2a9d8f", "#6c63ff", "#ff7f50",
            "#90be6d", "#d35d6e", "#5c7cfa", "#00b4d8", "#b07dac", "#7d8597", "#2c3e50"
        ]
        for idx, ds in enumerate(datasets):
            data = list(reversed(ds.get("data") or []))
            ax.barh(labels, data, left=current, color=palette[idx % len(palette)], label=ds.get("label"))
            current = [c + (v or 0) for c, v in zip(current, data)]
        ax.set_xlabel("贡献率(%)")
        ax.invert_yaxis()  # 最近月份置顶，阅读顺序更自然
        ax.legend(fontsize=8, loc="lower right")
        fig.tight_layout()
        figures["chart2"] = figure_to_base64(fig)
    except Exception:
        figures["chart2"] = None

    # 图3：失业率类型对比
    try:
        series = report_payload.get("unemployment_types_series") or []
        labels = [s.get("label") for s in series]
        prev_vals = [s.get("previous") for s in series]
        curr_vals = [s.get("current") for s in series]
        x = range(len(labels))
        width = 0.35
        fig, ax = plt.subplots(figsize=(7.5, 4))
        ax.bar([i - width/2 for i in x], prev_vals, width, label="上月", color="#8da9c4")
        ax.bar([i + width/2 for i in x], curr_vals, width, label="本月", color="#2f78c4")
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=30, ha="right")
        ax.set_ylabel("失业率(%)")
        ax.legend()
        fig.tight_layout()
        figures["chart3"] = figure_to_base64(fig)
    except Exception:
        figures["chart3"] = None

    # 图4：就业率/劳动参与率
    try:
        series = report_payload.get("employment_participation_series") or []
        labels = [s.get("date") for s in series]
        emp_vals = [s.get("employment_rate") for s in series]
        part_vals = [s.get("participation_rate") for s in series]
        fig, ax = plt.subplots(figsize=(7.5, 4))
        ax.plot(labels, emp_vals, color="#2f78c4", marker="o", linewidth=1.8, label="就业率(%)")
        ax.plot(labels, part_vals, color="#ef6c00", marker="o", linewidth=1.8, label="劳动参与率(%)")
        ax.set_ylabel("%")
        ax.tick_params(axis="x", rotation=45)
        ax.legend()
        fig.tight_layout()
        figures["chart4"] = figure_to_base64(fig)
    except Exception:
        figures["chart4"] = None

    return figures

def serialize_series(df: pd.DataFrame, value_key: str):
    """Serialize pandas dataframe to JSON-friendly structure."""
    records = []
    for _, row in df.iterrows():
        records.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            value_key: round(float(row[value_key]), 2)
        })
    return records

@app.route('/')
def index():
    """主页路由"""
    return render_template('index.html')

@app.route('/api/indicators')
def get_indicators():
    """获取所有经济指标的层级结构"""
    try:
        db = get_db_session()
        
        # 获取所有顶级分类（板块），按照sort_order排序
        top_categories = db.query(IndicatorCategory).filter(IndicatorCategory.parent_id.is_(None)).order_by(IndicatorCategory.sort_order).all()
        
        def build_category_hierarchy(category):
            """递归构建分类层级结构"""
            result = {
                'id': category.id,
                'name': category.name,
                'level': category.level,
                'sort_order': category.sort_order,
                'type': 'category',
                'children': []
            }
            
            # 获取子分类，按照sort_order排序
            child_categories = db.query(IndicatorCategory).filter(IndicatorCategory.parent_id == category.id).order_by(IndicatorCategory.sort_order).all()
            for child in child_categories:
                result['children'].append(build_category_hierarchy(child))
            
            # 获取该分类下的指标，按照sort_order排序
            indicators = db.query(EconomicIndicator).filter(EconomicIndicator.category_id == category.id).order_by(EconomicIndicator.sort_order).all()
            for indicator in indicators:
                result['children'].append({
                    'id': indicator.id,
                    'name': indicator.name,
                    'code': indicator.code,
                    'english_name': indicator.english_name,
                    'units': indicator.units,
                    'fred_url': indicator.fred_url,
                    'sort_order': indicator.sort_order,
                    'type': 'indicator'
                })
            
            return result
        
        # 构建完整的层级结构
        hierarchy = []
        for category in top_categories:
            hierarchy.append(build_category_hierarchy(category))
        
        db.close()
        return jsonify(hierarchy)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/summary')
def get_summary():
    """获取经济指标摘要数据"""
    try:
        db = get_db_session()
        
        # 获取所有指标
        indicators = db.query(EconomicIndicator).order_by(EconomicIndicator.id).all()
        
        result = []
        for indicator in indicators:
            # 获取最新数据点
            latest_data_point = db.query(EconomicDataPoint)\
                .filter(EconomicDataPoint.indicator_id == indicator.id)\
                .order_by(EconomicDataPoint.date.desc())\
                .first()
            
            # 获取数据点总数
            data_point_count = db.query(EconomicDataPoint)\
                .filter(EconomicDataPoint.indicator_id == indicator.id)\
                .count()
            
            result.append({
                'id': indicator.id,
                'name': indicator.name,
                'code': indicator.code,
                'units': indicator.units,
                'fred_url': indicator.fred_url,
                'latest_value': latest_data_point.value if latest_data_point else None,
                'latest_date': latest_data_point.date.strftime('%Y-%m-%d') if latest_data_point else None,
                'data_point_count': data_point_count
            })
        
        db.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/data')
def get_data():
    """获取经济数据点"""
    try:
        indicator_id = request.args.get('indicator_id')
        date_range = request.args.get('date_range', '3Y')  # 默认最近3年
        sort_order = request.args.get('sort_order', 'date_desc')  # 默认按日期降序
        
        db = get_db_session()
        
        # 构建查询
        query = db.query(
            EconomicIndicator.name.label('indicator_name'),
            EconomicIndicator.code.label('indicator_code'),
            EconomicIndicator.units,
            EconomicDataPoint.date,
            EconomicDataPoint.value
        ).join(EconomicDataPoint, EconomicDataPoint.indicator_id == EconomicIndicator.id)
        
        # 添加指标筛选
        if indicator_id:
            query = query.filter(EconomicDataPoint.indicator_id == indicator_id)
        
        # 处理时间范围
        if date_range != 'all':
            end_date = datetime.now()
            if date_range == '1Y':
                start_date = end_date - timedelta(days=365)
            elif date_range == '3Y':
                start_date = end_date - timedelta(days=365*3)
            elif date_range == '5Y':
                start_date = end_date - timedelta(days=365*5)
            elif date_range == '10Y':
                start_date = end_date - timedelta(days=365*10)
            
            query = query.filter(EconomicDataPoint.date >= start_date)
        
        # 处理排序
        if sort_order == 'date_desc':
            query = query.order_by(EconomicDataPoint.date.desc())
        elif sort_order == 'date_asc':
            query = query.order_by(EconomicDataPoint.date.asc())
        elif sort_order == 'value_desc':
            query = query.order_by(EconomicDataPoint.value.desc())
        elif sort_order == 'value_asc':
            query = query.order_by(EconomicDataPoint.value.asc())
        
        # 限制结果数量
        data_points = query.limit(1000).all()
        
        result = []
        for point in data_points:
            result.append({
                'indicator_name': point.indicator_name,
                'indicator_code': point.indicator_code,
                'units': point.units,
                'date': point.date.strftime('%Y-%m-%d'),
                'value': point.value
            })
        
        db.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/labor-market/report', methods=['POST'])
def generate_labor_market_report():
    """生成'新增非农就业+失业率'图表以及DeepSeek研报"""
    payload = request.get_json() or {}
    report_month = payload.get('report_month')
    parsed_month = parse_report_month(report_month)
    if not parsed_month:
        return jsonify({'error': '报告月份格式需为YYYY-MM'}), 400

    target_period = pd.Period(parsed_month, freq='M')

    try:
        chart_builder = get_labor_chart_builder()
        chart_payload = chart_builder.prepare_payload(as_of=parsed_month)
    except Exception as exc:
        return jsonify({'error': f'生成图表失败: {exc}'}), 500

    rate_series_summary = []
    try:
        rate_builder = get_unemployment_chart_builder()
        rate_payload = rate_builder.prepare_payload(as_of=parsed_month)
        for snap in rate_payload.snapshots:
            rate_series_summary.append({
                'label': snap.label,
                'code': snap.fred_code,
                'current': snap.current,
                'previous': snap.previous,
                'mom_delta': snap.mom_delta
            })
    except Exception as exc:
        rate_series_summary = []
    
    industry_contribution = {}
    try:
        industry_builder = get_industry_contribution_builder()
        contrib_payload = industry_builder.prepare_payload(as_of=parsed_month)
        industry_contribution = {
            'labels': contrib_payload.labels,
            'datasets': contrib_payload.datasets,
            'latest_period': contrib_payload.latest_period,
            'top_positive': contrib_payload.top_positive,
            'top_negative': contrib_payload.top_negative
        }
    except Exception as exc:
        industry_contribution = {'error': f'分行业贡献数据缺失: {exc}'}

    payems_row = select_month_row(chart_payload.payems_changes, target_period)
    unemployment_row = select_month_row(chart_payload.unemployment_rate, target_period)
    payems_value = float(payems_row['monthly_change_10k']) if payems_row is not None else None
    unemp_value = float(unemployment_row['value']) if unemployment_row is not None else None

    prev_period = target_period - 1
    yoy_period = target_period - 12

    # 就业率/劳动参与率（近2年窗口）
    employment_participation_series: list[dict] = []
    employment_value = None
    participation_value = None
    employment_mom = None
    participation_mom = None

    start_window = parsed_month - pd.DateOffset(years=2)
    employment_df = chart_builder._load_indicator_series("EMRATIO")
    participation_df = chart_builder._load_indicator_series("CIVPART")
    employment_df = employment_df[(employment_df["date"] >= start_window) & (employment_df["date"] <= parsed_month)].copy()
    participation_df = participation_df[(participation_df["date"] >= start_window) & (participation_df["date"] <= parsed_month)].copy()

    merged = pd.merge(
        employment_df.rename(columns={"value": "employment_rate"}),
        participation_df.rename(columns={"value": "participation_rate"}),
        on="date",
        how="outer",
    ).sort_values("date")

    for _, row in merged.iterrows():
        employment_participation_series.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            "employment_rate": float(row["employment_rate"]) if pd.notna(row.get("employment_rate")) else None,
            "participation_rate": float(row["participation_rate"]) if pd.notna(row.get("participation_rate")) else None,
        })

    emp_row = select_month_row(employment_df, target_period)
    part_row = select_month_row(participation_df, target_period)
    prev_emp_row = select_month_row(employment_df, prev_period)
    prev_part_row = select_month_row(participation_df, prev_period)
    employment_value = float(emp_row["value"]) if emp_row is not None else None
    participation_value = float(part_row["value"]) if part_row is not None else None
    employment_mom = format_delta(
        employment_value,
        float(prev_emp_row["value"]) if prev_emp_row is not None else None,
        decimals=2
    )
    participation_mom = format_delta(
        participation_value,
        float(prev_part_row["value"]) if prev_part_row is not None else None,
        decimals=2
    )
    prev_payems_row = select_month_row(chart_payload.payems_changes, prev_period)
    prev_unemp_row = select_month_row(chart_payload.unemployment_rate, prev_period)
    yoy_unemp_row = select_month_row(chart_payload.unemployment_rate, yoy_period)

    payems_mom = format_delta(
        payems_value,
        float(prev_payems_row['monthly_change_10k']) if prev_payems_row is not None else None,
        decimals=1
    )
    unemp_mom = format_delta(
        unemp_value,
        float(prev_unemp_row['value']) if prev_unemp_row is not None else None,
        decimals=2
    )
    unemp_yoy = format_delta(
        unemp_value,
        float(yoy_unemp_row['value']) if yoy_unemp_row is not None else None,
        decimals=2
    )

    headline_parts = []
    if payems_value is not None:
        headline_parts.append(f"非农就业增加{payems_value:.1f}万人")
    if unemp_value is not None:
        headline_parts.append(f"失业率{unemp_value:.1f}%")
    headline_summary = "，".join(headline_parts) if headline_parts else f"{report_month}缺少足够数据"

    # 构造LLM使用的数据摘要
    indicator_summaries = []
    ui_indicators = []
    if payems_value is not None:
        indicator_summaries.append(IndicatorSummary(
            name="新增非农就业",
            latest_value=f"{payems_value:.1f}",
            units="万人",
            mom_change=f"{payems_mom} 万人" if payems_mom else None,
            context="PAYEMS月度增量（万人）"
        ))
        ui_indicators.append({
            'name': '新增非农就业',
            'latest_value': f"{payems_value:.1f}",
            'units': '万人',
            'mom_change': payems_mom,
            'context': 'PAYEMS月度增量（万人）'
        })

    if unemp_value is not None:
        indicator_summaries.append(IndicatorSummary(
            name="失业率(U3)",
            latest_value=f"{unemp_value:.1f}",
            units="%",
            mom_change=f"{unemp_mom} ppts" if unemp_mom else None,
            yoy_change=f"{unemp_yoy} ppts" if unemp_yoy else None,
            context="UNRATE，经季调"
        ))
        ui_indicators.append({
            'name': '失业率(U3)',
            'latest_value': f"{unemp_value:.1f}",
            'units': '%',
            'mom_change': unemp_mom,
            'yoy_change': unemp_yoy,
            'context': 'UNRATE，经季调'
        })

    # 传入各类型失业率细分数据，提升LLM覆盖度
    for rate in rate_series_summary:
        if rate.get('current') is None:
            continue
        mom_delta = rate.get('mom_delta')
        indicator_summaries.append(IndicatorSummary(
            name=f"{rate.get('label')}失业率",
            latest_value=f"{rate['current']:.2f}",
            units="%",
            mom_change=f"{mom_delta:+.2f} ppts" if mom_delta is not None else None,
            context=f"代码 {rate.get('code')}"
        ))

    # 传入就业率与劳动参与率
    if employment_value is not None:
        indicator_summaries.append(IndicatorSummary(
            name="就业率",
            latest_value=f"{employment_value:.2f}",
            units="%",
            mom_change=f"{employment_mom} ppts" if employment_mom else None,
            context="EMRATIO，就业人口占工作年龄人口"
        ))
        ui_indicators.append({
            'name': '就业率',
            'latest_value': f"{employment_value:.2f}",
            'units': '%',
            'mom_change': employment_mom,
            'context': 'EMRATIO，就业人口占工作年龄人口'
        })
    if participation_value is not None:
        indicator_summaries.append(IndicatorSummary(
            name="劳动参与率",
            latest_value=f"{participation_value:.2f}",
            units="%",
            mom_change=f"{participation_mom} ppts" if participation_mom else None,
            context="CIVPART，劳动力占工作年龄人口"
        ))
        ui_indicators.append({
            'name': '劳动参与率',
            'latest_value': f"{participation_value:.2f}",
            'units': '%',
            'mom_change': participation_mom,
            'context': 'CIVPART，劳动力占工作年龄人口'
        })

    avg_payems = chart_payload.payems_changes["monthly_change_10k"].mean()
    avg_unemp = chart_payload.unemployment_rate["value"].mean()
    chart_commentary_parts = []
    if payems_value is not None and unemp_value is not None:
        chart_commentary_parts.append(
            f"图表覆盖{chart_payload.start_date:%Y-%m}至{chart_payload.end_date:%Y-%m}。"
            f"期间新增非农就业平均{avg_payems:.1f}万人，当前为{payems_value:.1f}万人；"
            f"失业率平均{avg_unemp:.1f}%，当前为{unemp_value:.1f}%."
        )

    if employment_value is not None and participation_value is not None:
        emp_avg = employment_df["value"].mean()
        part_avg = participation_df["value"].mean()
        chart_commentary_parts.append(
            f"就业率均值约{emp_avg:.2f}%，当前{employment_value:.2f}%；"
            f"劳动参与率均值约{part_avg:.2f}%，当前{participation_value:.2f}%。"
        )

    industry_commentary = ""
    if industry_contribution.get('labels') and not industry_contribution.get('error'):
        labels_range = (industry_contribution['labels'][0], industry_contribution['labels'][-1])
        latest_period = industry_contribution.get('latest_period')
        pos_text = "，".join(
            f"{item['label']} {item['value']:+.1f}%"
            for item in (industry_contribution.get('top_positive') or [])
        )
        neg_text = "，".join(
            f"{item['label']} {item['value']:+.1f}%"
            for item in (industry_contribution.get('top_negative') or [])
        )
        pieces = []
        if pos_text:
            pieces.append(f"主要拉动：{pos_text}")
        if neg_text:
            pieces.append(f"拖累：{neg_text}")
        industry_commentary = (
            f"图2覆盖{labels_range[0]}至{labels_range[1]}。"
            f"{latest_period or ''}月分行业贡献率显示，" + ("；".join(pieces) if pieces else "贡献结构缺乏显著差异。")
        )
        chart_commentary_parts.append(industry_commentary)

    chart_commentary = " ".join(part for part in chart_commentary_parts if part)

    fomc_points = []
    if payems_value is not None and avg_payems is not None:
        if payems_value >= avg_payems:
            fomc_points.append("就业增速仍高于三年均值，FOMC需要警惕劳动力需求的粘性。")
        else:
            fomc_points.append("非农就业增速回落至近三年均值下方，就业市场降温有助于抑制薪资压力。")
    if unemp_mom:
        if unemp_mom.startswith("+"):
            fomc_points.append("失业率小幅回升，劳动力闲置率的抬头或将缓解政策压力。")
        else:
            fomc_points.append("失业率继续走低，显示需求仍旧旺盛，可能延后宽松。")

    risk_points = []
    if payems_mom and payems_mom.startswith("-"):
        risk_points.append("关注企业招聘冻结对未来数月就业的拖累。")
    else:
        risk_points.append("持续强劲的招聘可能让工资黏性更顽固。")

    policy_focus = ReportFocus(
        fomc_implications=fomc_points,
        risks_to_watch=risk_points,
        market_reaction=[]
    )

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    report_text = None
    llm_error = None
    if deepseek_key:
        try:
            generator = build_economic_report()
            report_text = generator.generate_nonfarm_report(
                report_month=report_month,
                headline_summary=headline_summary,
                labor_market_metrics=indicator_summaries,
                policy_focus=policy_focus,
                chart_commentary=chart_commentary
            )
        except Exception as exc:
            llm_error = f"生成研报失败: {exc}"
    else:
        llm_error = "未配置DEEPSEEK_API_KEY，无法调用研报生成。"

    response = {
        'report_month': report_month,
        'headline_summary': headline_summary,
        'chart_window': {
            'start_date': chart_payload.start_date.strftime("%Y-%m-%d"),
            'end_date': chart_payload.end_date.strftime("%Y-%m-%d")
        },
        'indicators': ui_indicators,
        'chart_commentary': chart_commentary,
        'payems_series': serialize_series(chart_payload.payems_changes, "monthly_change_10k"),
        'unemployment_series': serialize_series(chart_payload.unemployment_rate, "value"),
        'unemployment_types_series': rate_series_summary,
        'employment_participation_series': employment_participation_series,
        'industry_contribution': industry_contribution,
        'report_text': report_text,
        'llm_error': llm_error
    }
    return jsonify(response)

@app.route('/api/chart-data')
def get_chart_data():
    """获取图表数据"""
    try:
        indicator_id = request.args.get('indicator_id')
        date_range = request.args.get('date_range', '3Y')  # 默认最近3年
        
        if not indicator_id:
            return jsonify({'error': '缺少指标ID参数'}), 400
        
        db = get_db_session()
        
        # 获取指标信息
        indicator = db.query(EconomicIndicator.name, EconomicIndicator.units).filter(EconomicIndicator.id == indicator_id).first()
        
        if not indicator:
            db.close()
            return jsonify({'error': '未找到指定的指标'}), 404
        
        indicator_name = indicator[0]
        indicator_units = indicator[1]
        
        # 构建查询
        query = db.query(EconomicDataPoint.date, EconomicDataPoint.value)\
            .filter(EconomicDataPoint.indicator_id == indicator_id)
        
        # 处理时间范围
        if date_range != 'all':
            end_date = datetime.now()
            if date_range == '1Y':
                start_date = end_date - timedelta(days=365)
            elif date_range == '3Y':
                start_date = end_date - timedelta(days=365*3)
            elif date_range == '5Y':
                start_date = end_date - timedelta(days=365*5)
            elif date_range == '10Y':
                start_date = end_date - timedelta(days=365*10)
            
            query = query.filter(EconomicDataPoint.date >= start_date)
        
        # 按日期排序
        data_points = query.order_by(EconomicDataPoint.date.asc()).all()
        
        dates = []
        values = []
        
        for point in data_points:
            dates.append(point.date.strftime('%Y-%m-%d'))
            values.append(point.value)
        
        db.close()
        return jsonify({
            'indicator_name': indicator_name,
            'indicator_units': indicator_units,
            'dates': dates,
            'values': values
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/refresh-data', methods=['POST'])
def refresh_data():
    """刷新数据（模拟实现）"""
    try:
        # 实际应用中这里应该包含数据更新逻辑
        # 示例：从外部API获取最新数据并存储到数据库
        # 暂时保留模拟响应
        return jsonify({'message': '数据刷新任务已启动'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/labor-market/report.pdf', methods=['POST'])
def export_labor_market_report_pdf():
    """使用Playwright生成PDF（基于已生成的研报数据）"""
    payload = request.get_json() or {}
    report_data = payload.get("report_data") or {}
    if not report_data:
        return jsonify({'error': '缺少report_data参数，请先生成研报后再导出'}), 400

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return jsonify({'error': '缺少playwright依赖，请先安装：pip install playwright && playwright install chromium'}), 500

    report_month = report_data.get("report_month") or datetime.utcnow().strftime("%Y-%m")
    tz_cn = timezone(timedelta(hours=8))
    exported_at = datetime.now(tz_cn).strftime("%Y-%m-%d %H:%M")

    charts = build_pdf_charts(report_data)
    report_html = simple_markdown_to_html(report_data.get("report_text") or "")
    pdf_html = render_template(
        'report_pdf.html',
        report=report_data,
        report_html=inject_figures_into_report_html(report_html, charts),
        charts=charts,
        export_month=report_month,
        exported_at=exported_at
    )

    try:
        header_template = """
        <style>
          .pdf-head { font-family: 'Times New Roman', 'KaiTi', serif; font-size: 12px; width: 100%; padding: 10px 22px 8px; color: #4a5568; display:flex; justify-content: space-between; align-items: center; box-sizing:border-box; }
          .pdf-head .brand { display:flex; align-items:center; gap:14px; font-weight:700; letter-spacing:0.35px; }
          .pdf-head .icon { width:30px; height:30px; border-radius:10px; background:linear-gradient(135deg,#1b2f60,#2f6bff); position:relative; box-shadow:0 8px 20px rgba(31,63,130,0.24), inset 0 1px 0 rgba(255,255,255,0.15); display:grid; place-items:center; }
          .pdf-head .icon::after { content:\"\"; position:absolute; inset:4px; border-radius:8px; border:1px solid rgba(255,255,255,0.35); box-shadow:inset 0 0 0 1px rgba(0,0,0,0.06); }
          .pdf-head .icon span { position:relative; z-index:1; color:#f9fbff; font-size:13px; font-weight:800; font-family:'Times New Roman', serif; letter-spacing:0.4px; }
          .pdf-head .tagline { font-weight:650; color:#374151; font-size: 11.5px; }
        </style>
        <div class="pdf-head">
          <div class="brand"><span class="icon"><span>F</span></span><span>Fed Tools · 非农研判</span></div>
          <div class="tagline">智能洞察 · 自动撰写</div>
        </div>
        """
        footer_template = """
        <style>
          .pdf-foot { font-family: 'Times New Roman', 'KaiTi', serif; font-size:11.5px; width:100%; padding:8px 22px 8px; color:#4b5563; text-align:right; box-sizing:border-box; }
        </style>
        <div class="pdf-foot">第 <span class="pageNumber"></span> / <span class="totalPages"></span> 页</div>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(pdf_html, wait_until="load")
            try:
                pdf_bytes = page.pdf(
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template=header_template,
                    footer_template=footer_template,
                    margin={"top": "20mm", "bottom": "22mm", "left": "16mm", "right": "16mm"}
                )
            except Exception:
                app.logger.exception("带页眉/页码导出失败，使用降级方案重试")
                pdf_bytes = page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "20mm", "bottom": "22mm", "left": "16mm", "right": "16mm"}
                )
            browser.close()
    except Exception as exc:
        app.logger.exception("生成PDF失败")
        return jsonify({'error': f'生成PDF失败: {exc}'}), 500

    response = Response(pdf_bytes, mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename=nonfarm_report_{report_month}.pdf'
    return response

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
