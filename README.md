# 美妆客服工作台 v0.3（L'Oréal Service Atelier）

一个本机比赛演示系统：Customer 入口运行在 `8000`，Customer Service 工作台运行在 `8001`；两端共享同一个 SQLite 数据库和媒体目录。v0.3 在 v0.2 的四页工作台之上，新增了情绪风险看板、AI 接待辅助/会话分析，以及大字号演示视觉层（v0.3 Atelier 皮肤）。

## 功能总览

- **8000（客户端）**：客户聊天、商品浏览、我的订单、可公开的售后进度。
- **8001（客服工作台）**：五个可互相跳转的页面。
  - `/workspace/chat`：客户沟通。会话队列 + 聊天区 + 右侧信息栏（客户全景、服务轨迹、AI 分析、接待辅助、关联事实），支持全文检索。
  - `/workspace/orders`：订单管理。订单搜索、物流信息、关联售后跳转。
  - `/workspace/after-sales`：售后管理。五类售后工单、状态流转与处理时间线。
  - `/workspace/products`：商品档案与相关订单入口。
  - `/workspace/risk`：情绪风险跟踪看板。预警 KPI、近 7 日趋势、预警列表、单条风险详情（依据完整聊天生成的情绪与处理判断）。
- **AI 能力**
  - 接待辅助 / AI 分析：按会话生成客户意图、客服处理、当前进度、事实核验、建议回复与情绪判断。
  - 客户全景：整合消费、订单、咨询与售后历史。
  - 情绪风险看板：预警计数、趋势与逐条风险分析。
  - AI 分析结果服务端持久化：每个会话的分析结果存为 `data/assistant/<会话ID>/summary.json`；打开会话时优先读取存档，刷新页面不再重复分析，只有点击「重新分析」才会重新调用并覆盖存档。
- 正式 Excel 工作簿采用「预览校验 → 确认提交」两步导入，重复导入不会重复增加数据。
- 旧版聊天、媒体、商品和订单 API 保持兼容；已有 SQLite 数据通过 Alembic 自动升级并保留。

## 安装与启动

要求：本机已安装 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync
```

一键启动两个端口：

```powershell
.\scripts\start_all.ps1
```

或分别启动：

```powershell
.\scripts\start_customer.ps1
.\scripts\start_customer_service.ps1
```

绕过 PowerShell 脚本直接启动：

```powershell
uv run python -m app.backend.cli --role customer
uv run python -m app.backend.cli --role customer_service
```

- 数据库默认 `data/app.db`，首次启动自动创建；旧版本数据库自动迁移。演示前建议备份一次。
- 访问入口：客户端 `http://127.0.0.1:8000`，客服端 `http://127.0.0.1:8001/workspace/chat`。
- API 文档：`http://127.0.0.1:8000/docs`、`http://127.0.0.1:8001/docs`。

## LLM 配置（可选）

AI 分析默认走 OpenAI 兼容接口（DashScope）。在项目根目录放 `.env` 或设置环境变量：

```text
LLM_API_KEY=sk-...            # 或 DASHSCOPE_API_KEY
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.7-flash
```

未配置 API Key 时，相关分析自动降级为离线规则判断，页面会标注「已使用快速离线判断」。

## 导入比赛工作簿

1. 打开订单管理、售后管理或商品管理页。
2. 点击「导入工作簿」。
3. 选择 `赛题 1：数据共情者-业务数据.xlsx`。
4. 查看七张业务表的数量和逐行错误。
5. 校验通过后才会出现「确认写入数据库」按钮。

正式工作簿的预期结果：138 个会话、998 条聊天、113 个订单、80 张工单（24/13/15/10/18）以及 20 个订单商品档案。字段契约见 [docs/data-contract-v0.2.md](docs/data-contract-v0.2.md)。

## 数据目录

```text
data/
├── app.db                                   # SQLite（会话、消息、订单、工单、商品）
├── media/                                   # 聊天媒体文件
└── assistant/
    └── <会话ID>/summary.json                 # 每个会话的 AI 分析存档
```

- 存档目录可用 `APP_ASSISTANT_DIR` 覆盖（默认 `./data/assistant`）。
- 分析接口：`POST /api/v1/management/conversations/{id}/assistance` 重新分析并写入存档；`GET` 同路径读取存档（未存过返回 404）。

## 数据与隐私边界

- 工单内部字段和管理写接口仅在 8001 开放。
- 8000 只返回固定白名单字段：工单号、公开类型、状态、更新时间、补发物流、已确认退款结果。
- 处理人、内部备注、支付宝信息、风控字段和不良反应详情不会返回给客户侧。
- 当前隔离依靠端口角色，适用于本机比赛演示；若开放到局域网或公网，必须先补齐账号、权限与审计。

## 开发检查

```powershell
uv run ruff check .
uv run pytest -q
node --check app/frontend/static/service_workspace.js
node --check app/frontend/static/customer.js
```

## 代码目录

```text
app/
├── backend/
│   ├── agent/            # AI 接待辅助 agent 与 LLM Provider
│   ├── api/              # 路由：conversations / messages / management / work_orders / emotion_analysis 等
│   ├── imports/          # Excel 工作簿导入
│   ├── migrations/       # Alembic 迁移
│   ├── config.py         # Settings（含 assistant_dir）
│   ├── main.py           # 应用工厂与页面路由
│   ├── models.py
│   ├── realtime.py       # WebSocket 实时消息
│   └── schemas.py
└── frontend/
    ├── customer.html            # 8000 客户端
    ├── customer_service.html    # 8001 工作台外壳
    └── static/                  # service_workspace_v03.css / service_workspace.js / api.js 等
```
