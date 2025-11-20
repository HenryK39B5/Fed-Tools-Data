import base64
import io
import os
import sys
from calendar import monthrange
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import pandas as pd
from flask import Flask, render_template, jsonify, request
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
    chart_commentary = (
        f"图表覆盖{chart_payload.start_date:%Y-%m}至{chart_payload.end_date:%Y-%m}。"
        f"期间新增非农就业平均{avg_payems:.1f}万人，"
        f"当前为{payems_value:.1f}万人；失业率平均{avg_unemp:.1f}%，"
        f"当前为{unemp_value:.1f}%."
    ) if payems_value is not None and unemp_value is not None else ""

    if employment_value is not None and participation_value is not None:
        emp_avg = employment_df["value"].mean()
        part_avg = participation_df["value"].mean()
        chart_commentary += (
            f" 就业率均值约{emp_avg:.2f}%，当前{employment_value:.2f}%；"
            f"劳动参与率均值约{part_avg:.2f}%，当前{participation_value:.2f}%。"
        )

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
