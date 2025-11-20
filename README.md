# FOMC经济数据分析项目

## 项目概述
本项目收集、存储和分析与FOMC决策相关的经济数据，并提供Web可视化与自动化研报生成功能（DeepSeek LLM）。

## 项目结构（核心文件）
```
├─ config/                         # 全局配置占位（保持包结构）
├─ data/                           # 数据摄取与预处理
│   ├─ charts/                     # 生成静态图的数据管道
│   │   ├─ nonfarm_jobs_chart.py   # PAYEMS + UNRATE 组合图（图1数据来源）
│   │   └─ unemployment_rate_comparison.py  # U1~U6 对比（图2数据来源）
│   ├─ collect_economic_data_from_excel.py  # 读取 Excel 指标层级并写库
│   ├─ data_updater.py             # 增量更新调度
│   ├─ category_manager.py         # 指标分类/排序维护
│   ├─ fred_api.py                 # 轻量 FRED 客户端
│   ├─ rate_limited_fred_api.py    # 带限速/批量的 FRED 客户端
│   ├─ preprocessing.py            # 清洗、单位标准化
│   └─ visualization.py            # 本地探索式可视化
├─ database/                       # ORM 定义
│   ├─ base.py
│   ├─ connection.py
│   └─ models.py
├─ docs/                           # 参考资料
│   ├─ US Economic Indicators with FRED Codes.xlsx
│   └─ cpi_weights.csv
├─ reports/                        # 研报生成
│   ├─ report_generator.py         # 构造Prompt + 调用DeepSeek
│   └─ deepseek_client.py          # DeepSeek API封装
├─ webapp/                         # Flask 前端
│   ├─ app.py                      # API + 前端路由
│   ├─ templates/index.html        # 单页应用（Chart.js、研报渲染）
│   └─ fomc_data.db                # 运行时数据库（与根目录同名文件一致）
├─ fomc_data.db                    # SQLite 数据库（根目录副本）
├─ init_database.py                # 初始化库
├─ process_all_indicators.py       # 一键全量/增量处理入口
├─ update_fred_urls.py             # FRED链接修正工具
└─ requirements.txt                # 依赖
```

## 核心Python模块功能一览

| 模块 | 作用 | 典型入口 |
| --- | --- | --- |
| `data/collect_economic_data_from_excel.py` | 解析 `docs/US Economic Indicators...xlsx`，创建分类层级并全量抓取指标后写入数据库。适合冷启动或重建数据库。 | `python data/collect_economic_data_from_excel.py --excel docs/...xlsx` |
| `data/data_updater.py` | 高级增量更新器，循环请求指标、调用预处理逻辑并把新数据落库；整合限速 API、分类工具及数据库层。 | `python data/data_updater.py --days-back 365` |
| `data/fred_api.py` | 最基础的FRED API封装（无限速、无默认日期），提供 `get_series / get_series_info / search_series` 等方法，便于单脚本快速调用。 | 被 `collect_economic_data_from_excel.py` 引用 |
| `data/rate_limited_fred_api.py` | 在基础API之上增加速率限制、默认日期区间、批量抓取（`get_multiple_series`）与日志，保证长任务稳定。 | 被 `data_updater.py`、`process_all_indicators.py` 等增量任务引用 |
| `data/preprocessing.py` | `DataPreprocessor` 类：负责对下载的原始序列做去重、频率对齐、单位映射及插值等标准化处理。 | 在 `data_updater.py`、`collect_economic_data_from_excel.py` 中实例化 |
| `data/category_manager.py` | 维护指标分类、排序、父子关系的工具，确保数据库与Excel结构一致。 | `process_all_indicators.py` |
| `database/*.py` | SQLAlchemy 基础设施：`base.py` 提供 Base，`models.py` 定义 3 张核心表，`connection.py` 提供 `get_db` 和 engine。 | 所有写库脚本 |
| `process_all_indicators.py` | 一键运行全流程：同步分类、抓取指标、执行预处理、写库，可通过参数选择起始日期和是否全量刷新。 | `python process_all_indicators.py --start-date 2015-01-01` |
| `webapp/app.py` | Flask Web 界面，展示数据库中的指标、曲线和表格。 | `python webapp/app.py` |

### 关于 FRED API 模块是否重复？

项目中保留了两个FRED客户端，它们面向不同场景，并非简单重复：

- `fred_api.py`：轻量封装，便于在一次性脚本或Notebook中快速调用 FRED 接口，不包含限速或批量逻辑。当前 `collect_economic_data_from_excel.py` 依赖该实现，以保持脚本流程直观。
- `rate_limited_fred_api.py`：具备调用频控、默认日期回填、批量抓取辅助等稳态运行所需特性，是 `data_updater.py`、`process_all_indicators.py` 等长时间运行脚本的默认客户端。

因此 `fred_api.py` 仍有保留价值；如果未来所有脚本都迁移到带限速版本，可以再考虑统一接口后删除。

## 安装依赖
```bash
pip install -r requirements.txt
```

## 环境配置
1. 在FRED网站注册账户并获取API密钥: https://fred.stlouisfed.org/docs/api/api_key.html
2. 将API密钥添加到.env文件中:
```
FRED_API_KEY=your_api_key_here
```

## 使用说明

### 1. 初始化数据库
```bash
python init_database.py
```

### 2. 批量处理所有经济指标（推荐）
`process_all_indicators.py` 现在同时负责维护指标层级、排序和数据更新，可使用参数控制抓取范围：
```bash
# 拉取默认（2010至最新）数据
python process_all_indicators.py

# 指定历史区间或全量重建示例
python process_all_indicators.py --start-date 2010-01-01 --full-refresh
```

### 3. 启动Web数据浏览器
```bash
cd webapp
python app.py
```
访问 http://localhost:5000 查看数据浏览器。

## 数据库结构

### indicator_categories 表
存储经济指标的分类信息:
- id: 主键
- name: 分类名称
- level: 分类层级
- parent_id: 父分类ID

### economic_indicators 表
存储经济指标的定义信息:
- id: 主键
- name: 指标名称
- code: 指标代码
- description: 指标描述
- frequency: 数据频率
- units: 单位
- seasonal_adjustment: 季节性调整信息
- category_id: 分类ID

### economic_data_points 表
存储具体的经济数据点:
- id: 主键
- indicator_id: 外键，关联到economic_indicators表
- date: 数据日期
- value: 数据值

## 收集的经济指标

### 非农就业相关指标（18个）
1. **非农就业总数** (PAYEMS)
2. **分部门新增就业**（14个部门指标）:
   - 采矿业 (USMINE)
   - 建筑业 (USCONS)
   - 制造业 (MANEMP)
   - 批发业 (USWTRADE)
   - 零售业 (USTRADE)
   - 运输仓储业 (USTPU)
   - 公用事业 (CES4422000001)
   - 信息业 (USINFO)
   - 金融活动 (USFIRE)
   - 专业和商业服务 (USPBS)
   - 教育和保健服务 (USEHS)
   - 休闲和酒店业 (USLAH)
   - 其他服务业 (USSERV)
   - 政府 (USGOVT)
3. **失业率指标**（6个U系列指标）:
   - U-3 (UNRATE)
   - U-1 (U1RATE)
   - U-2 (U2RATE)
   - U-4 (U4RATE)
   - U-5 (U5RATE)
   - U-6 (U6RATE)
4. **劳动力市场指标**:
   - 劳动参与率 (CIVPART)
   - 就业率 (EMRATIO)

### CPI相关指标（33个）
1. **总体CPI**:
   - CPI（季调后）(CPIAUCSL)
   - 核心CPI (CPILFESL)
2. **分项CPI**（31个细分指标）:
   - 食品 (CPIUFDSL)
   - 家庭食品 (CUSR0000SAF11)
   - 在外饮食 (CUUR0000SEFV)
   - 能源 (CPIENGSL)
   - 能源商品 (CUSR0000SACE)
   - 燃油和其他燃料 (CUSR0000SEHE)
   - 发动机燃料（汽油） (CUSR0000SETB)
   - 能源服务 (CUSR0000SEHF)
   - 电力 (CUSR0000SEHF01)
   - 公用管道燃气服务 (CUSR0000SEHF02)
   - 核心商品（不含食品和能源类） (CUSR0000SACL1E)
   - 家具和其他家用产品 (CUUS0000SAH31)
   - 服饰 (CPIAPPSL)
   - 交通工具（不含汽车燃料） (CUUS0000SATCLTB)
   - 新车 (CUSR0000SETA01)
   - 二手汽车和卡车 (CUSR0000SETA02)
   - 机动车部件和设备 (CUSR0000SETC)
   - 医疗用品 (CUSR0000SAM1)
   - 酒精饮料 (CUSR0000SAF116)
   - 核心服务（不含能源） (CUSR0000SASLE)
   - 住所 (CUSR0000SAH1)
   - 房租 (CUSR0000SEHA)
   - 水、下水道和垃圾回收 (CUSR0000SEHG)
   - 家庭运营 (CUSR0000SAH3)
   - 医疗服务 (CUSR0000SAM2)
   - 运输服务 (CUSR0000SAS4)

## Web数据浏览器

项目包含一个功能完整的Web界面，用于直观地浏览和分析FOMC相关经济数据。

### 功能特性
1. **响应式设计**：适配桌面和移动设备
2. **指标选择**：从51个关键经济指标中选择查看
3. **时间范围筛选**：支持1年、3年、5年、10年和全部数据的时间范围
4. **数据排序**：支持按日期或数值进行升序/降序排列
5. **可视化图表**：使用Chart.js实现折线图和柱状图展示
6. **数据表格**：以表格形式展示详细数据点
7. **实时刷新**：支持手动刷新获取最新数据
8. **数据摘要**：显示关键指标的最新值和趋势信息
9. **单位显示**：所有指标都包含正确的单位信息，显示在图表标题和数据表格中

### 技术实现
- **后端**：Python Flask框架
- **前端**：HTML5, CSS3, JavaScript
- **数据库**：SQLAlchemy ORM
- **可视化**：Chart.js
- **UI框架**：Bootstrap 5

## API调用频率控制

项目实现了API调用频率控制机制，避免超出FRED API的调用限制：

1. **限速FRED API**：`rate_limited_fred_api.py` 实现了API调用频率控制
2. **批量处理脚本**：`process_all_indicators.py` 支持批量处理多个指标
3. **错误处理**：实现了重试机制和错误处理

## 数据完整性

项目确保所有经济指标都包含正确的单位信息：
- 分部门新增就业指标：单位为"Thousands of Persons, Seasonally Adjusted"
- 失业率指标：单位为"Percent, Seasonally Adjusted"
- CPI相关指标：包含适当的单位信息

## 开发计划
1. ~~开发数据可视化功能，创建经济指标的趋势图表~~ (已完成)
2. ~~实现定期自动数据收集功能~~ (已完成)
3. ~~添加更多经济指标到收集列表~~ (已完成)
4. ~~开发Web界面以更直观地展示数据~~ (已完成)
5. ~~确保所有指标包含正确的单位信息~~ (已完成)
6. 实现数据分析和预测功能
7. 添加更多数据源
8. 优化API调用效率
9. 添加数据导出功能
10. 实现多语言支持
