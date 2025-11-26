# 联邦货币 LLM 委员会（FOMC）项目

以“工具 + 教学 + 沉浸式流程”帮助用户理解美联储货币政策决策。愿景、交互骨架与路线图详见 `docs/PROJECT_COMPASS.md`。

## 仓库结构
- `docs/`：项目指南针与公共文档。
- `packages/data/`：FED-TOOLS-DATA 模块（数据抓取/清洗、可视化、研报、PDF）。现阶段的可运行部分。
- `packages/`（预留）：`models`、`agents`、`common` 等共享包。
- `apps/`（预留）：`web`、`api` 等应用层。
- `fomc_data.db`：默认 SQLite 数据库，供数据模块及未来应用共享。

## 先行可用模块：packages/data
- 主要功能：抓取/更新 FRED 数据、生成非农与 CPI 研报、Web 界面展示与 PDF 导出。
- 快速使用（在仓库根目录执行）：  
  ```bash
  pip install -r packages/data/requirements.txt
  python packages/data/init_database.py
  python packages/data/process_all_indicators.py
  cd packages/data/webapp && python app.py
  ```
- 详细说明见 `packages/data/README.md`。

## 近期计划
- 按指南针建立三模式骨架：体验（历史会议模拟）/ 学习（美联储 101）/ 工具（工具箱）。
- 接入 FedWatch 与规则模型，串联数据 → 研报 → 模型 → 讨论 → 决议/复盘。
- 拆分共享包与应用层（`packages/models`、`packages/agents`、`apps/web`、`apps/api`）。
