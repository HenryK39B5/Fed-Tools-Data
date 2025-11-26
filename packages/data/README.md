# FOMC 宏观数据情报工作台（packages/data）

本目录是“联邦货币 LLM 委员会（Federal mOnetary llM Committee）”的 **数据与研报模块**，提供数据抓取/清洗、可视化、研报生成与 PDF 导出。项目整体愿景、三模式骨架与路线图见仓库根目录 `docs/PROJECT_COMPASS.md`。

## 核心功能
- 经济指标浏览：按分类挑选指标，查看趋势图和数据表，附带 FRED 链接。
- 研报生成：输入月份即可生成专题研报  
  - 非农：自动绘制新增就业、行业贡献、失业率等图表，生成解读。  
  - CPI：自动绘制同比/环比图表，生成分项拉动表。
- PDF 导出：非农与 CPI 研报均可一键导出（包含图表和表格）。
- 数据更新：脚本化抓取与增量更新，数据存储在本地 SQLite。

## 简明架构
- 数据层：从 FRED 抓取并清洗，存入本地 SQLite；`process_all_indicators.py` 负责一键更新。
- 服务层：Flask 提供 API 和页面渲染；`webapp/app.py` 同时渲染图表、生成 PDF。
- 前端层：单页式界面（`webapp/templates/index.html`），显示图表、表格并触发研报/PDF 导出。
- AI 生成（可选）：如配置 DeepSeek API，可自动写研报正文；未配置时仍可生成图表和表格。

## 快速上手
> 建议在仓库根目录执行命令，以便正确找到根目录下的 `docs/` 与 `fomc_data.db`（默认 SQLite）。

1) 安装依赖  
```bash
pip install -r packages/data/requirements.txt
```
2) 配置 `.env`（文本文件即可）  
```
FRED_API_KEY=你的FRED密钥       # https://fred.stlouisfed.org
DEEPSEEK_API_KEY=可选，用于自动写研报
```
3) 初始化并更新数据  
```bash
python packages/data/init_database.py
python packages/data/process_all_indicators.py            # 默认从 2010 年开始抓取
# 如需指定起点：python packages/data/process_all_indicators.py --start-date 2015-01-01
```
4) 启动 Web 工作台  
```bash
cd packages/data/webapp
python app.py
# 浏览器打开 http://localhost:5000
```

## 如何生成研报
- 非农研报：在页面选择月份，点击“生成非农研报”→ 可查看并导出 PDF。
- CPI 研报：在页面选择月份，点击“生成CPI图表与研判”→ 可查看并导出 PDF（含分项拉动表、可视化条形+数值）。
- 若未设置 DEEPSEEK_API_KEY，仍可生成图表和表格，正文会使用简短占位描述。

## 目录速览
```
packages/data/data/          数据抓取与清洗；charts/ 内含各类图表的数据管道
packages/data/database/      SQLAlchemy 模型定义
packages/data/reports/       研报生成与提示词（DeepSeek）
packages/data/webapp/        Flask 后端与前端模板（index.html 为主要页面）
packages/data/requirements.txt  依赖列表
```

## 数据架构与更新操作说明
- **数据存储**：本地 SQLite（`fomc_data.db`），模型定义见 `database/models.py`。`EconomicDataPoint` 对 `indicator_id + date` 有唯一约束，避免重复。
- **元数据与分类**：Excel (`docs/US Economic Indicators with FRED Codes.xlsx`) 是指标清单。`data/indicator_sync_pipeline.py` 负责读取 Excel、创建/更新分类与指标；`data/category_manager.py` 保持既定层级与排序。
- **数据抓取**：`data/data_updater.py` 只补缺口并可全量刷新，调用带限流的 `data/rate_limited_fred_api.py`。避免直接重刷长区间。
- **统一入口**：`process_all_indicators.py` 现在只是薄封装，实际工作由 `IndicatorSyncPipeline` 完成（元数据同步 + 增量补数）。
- **其他工具**：`init_database.py` 建表；`update_fred_urls.py` 为指标补充 FRED 链接。

### 常用命令（含典型场景）
- 全量同步（默认从 2010-01-01 开始，按 Excel 清单增量补缺）：  
  `python process_all_indicators.py`
- 只更新最新一个月（例：库里最新是 2025-08，想补 2025-09）：  
  `python process_all_indicators.py --start-date 2025-08-01 --end-date 2025-09-30`  
  增量抓取会跳过已存在的日期；`--end-date` 可省略，默认抓到当前日期。
- Excel 新增了指标并希望补齐历史：  
  1) 在仓库根目录的 `docs/US Economic Indicators with FRED Codes.xlsx` 中新增行，保持列名/结构：`板块`、`经济指标`、`Indicator`、`FRED 代码`；分类行的 FRED 代码应为空或与指标名相同。  
  2) 执行 `python packages/data/process_all_indicators.py --start-date 2010-01-01`（或更早，如 2000-01-01）。新增指标会被创建，旧指标保持不变。开始日期取决于你希望覆盖的最早时间，增量逻辑会避免重复插入。
- 补入更早年份的数据（例：要从 2000 年开始补全历史）：  
  `python packages/data/process_all_indicators.py --start-date 2000-01-01 --full-refresh`  
  `--full-refresh` 会在拉取前清空各指标已存数据再重拉；若只想补缺口，可去掉该参数。

## 注意事项
- PDF 导出默认无书签/大纲；如需书签可在导出后自行处理。
- 本地默认使用 SQLite，生产可替换为其他数据库（调整 SQLAlchemy 连接字符串）。
- 默认数据库文件存放在仓库根目录 `fomc_data.db`，便于其他应用共享；若修改位置，请同步连接字符串或工作目录。
