# 美妆客服工作台 v0.2

这是一个本机比赛演示系统。Customer 入口运行在 `8000`，Customer Service 工作台运行在 `8001`；两端共享同一个 SQLite 数据库和媒体目录。

## v0.2 有什么

- 8000：客户聊天、商品、我的订单、可公开的售后进度。
- 8001：四个可互相跳转的客服页面。
  - `http://127.0.0.1:8001/workspace/chat`：客户沟通、全文检索、订单/商品/售后提示卡。
  - `http://127.0.0.1:8001/workspace/orders`：订单搜索、物流与关联售后。
  - `http://127.0.0.1:8001/workspace/after-sales`：五类售后工单、状态流转与处理时间线。
  - `http://127.0.0.1:8001/workspace/products`：商品档案与相关订单入口。
- 正式 Excel 工作簿采用“预览校验 → 确认提交”两步导入。重复导入不会重复增加数据，历史聊天不会逐条触发实时通知。
- 旧版聊天、媒体、商品和订单 API 保持兼容；已有 SQLite 数据会通过 Alembic 自动升级并保留。

## 安装与启动

要求：本机已安装 `uv`。

```powershell
uv sync
```

启动两个端口：

```powershell
.\scripts\start_all.ps1
```

也可以分别启动：

```powershell
.\scripts\start_customer.ps1
.\scripts\start_customer_service.ps1
```

数据库默认使用 `data/app.db`。首次启动会创建 v0.2 结构；旧 v0.1 数据库会自动运行版本化迁移。建议比赛演示前备份一次 `data/app.db`。

## 导入比赛工作簿

1. 打开订单管理、售后管理或商品管理页。
2. 点击“导入工作簿”。
3. 选择 `赛题 1：数据共情者-业务数据.xlsx`。
4. 查看七张业务表的数量和逐行错误。
5. 只有校验通过后，“确认写入数据库”按钮才会出现。

正式工作簿的预期结果：138 个会话、998 条聊天、113 个订单、80 张工单（24/13/15/10/18）以及 20 个订单商品档案。详细字段契约见 [docs/data-contract-v0.2.md](docs/data-contract-v0.2.md)。

## 数据与隐私边界

- 工单内部字段和管理写接口仅在 8001 开放。
- 8000 只返回固定白名单字段：工单号、公开类型、状态、更新时间、补发物流、已确认退款结果。
- 处理人、内部备注、支付宝信息、风控字段和不良反应详情不会返回给客户侧。
- 当前限制依靠端口角色，适用于本机比赛演示，不是真实登录鉴权。若开放到局域网或公网，必须先增加账号、权限与审计身份。

## 开发检查

```powershell
uv run ruff check .
uv run pytest -q
node --check app/frontend/static/service_workspace.js
node --check app/frontend/static/customer.js
```

API 文档：

- Customer：`http://127.0.0.1:8000/docs`
- Customer Service：`http://127.0.0.1:8001/docs`

## 代码目录

后端代码统一放在 `app/backend/`：

```text
app/
├── __init__.py
├── backend/
│   ├── api/
│   ├── imports/
│   ├── migrations/
│   ├── alembic.ini
│   ├── cli.py
│   ├── config.py
│   ├── db.py
│   ├── main.py
│   ├── models.py
│   ├── realtime.py
│   └── schemas.py
└── frontend/
```

需要绕过 PowerShell 脚本直接启动时，统一使用新入口：

```powershell
uv run python -m app.backend.cli --role customer
uv run python -m app.backend.cli --role customer_service
```
