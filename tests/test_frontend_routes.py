from fastapi.testclient import TestClient


def test_root_page_matches_backend_role(app_pair):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_app) as customer, TestClient(customer_service_app) as service:
        customer_page = customer.get("/")
        service_page = service.get("/")

        assert customer_page.status_code == 200
        assert customer_page.headers["cache-control"] == "no-store, max-age=0"
        assert customer_page.headers["pragma"] == "no-cache"
        assert 'data-page-role="customer"' in customer_page.text
        assert 'data-page-role="customer_service"' not in customer_page.text

        assert service_page.status_code == 200
        assert len(service_page.history) == 1
        assert str(service_page.url).endswith("/workspace/chat?ui=20260902-2")
        assert service_page.headers["cache-control"] == "no-store, max-age=0"
        assert service_page.headers["pragma"] == "no-cache"
        assert 'data-page-role="customer_service"' in service_page.text
        assert 'data-page-role="customer"' not in service_page.text


def test_frontend_static_assets_and_existing_docs_remain_available(app_pair):
    customer_app, _ = app_pair
    with TestClient(customer_app) as client:
        assert client.get("/static/styles.css").status_code == 200
        assert client.get("/static/api.js").status_code == 200
        assert client.get("/static/not-found.css").status_code == 404
        assert client.get("/docs").status_code == 200


def test_customer_service_has_five_direct_workspace_routes(app_pair):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_service_app) as client:
        for route, label in {
            "/workspace/chat": "客户沟通",
            "/workspace/orders": "订单管理",
            "/workspace/after-sales": "售后管理",
            "/workspace/products": "商品管理",
            "/workspace/risk": "风险预警跟踪看板",
        }.items():
            page = client.get(route)
            assert page.status_code == 200
            assert len(page.history) == 1
            assert "ui=20260902-2" in str(page.url)
            assert page.headers["cache-control"] == "no-store, max-age=0"
            assert page.headers["pragma"] == "no-cache"
            assert label in page.text
            assert 'data-page-role="customer_service"' in page.text
        assert client.get("/static/service_workspace.js").status_code == 200

    with TestClient(customer_app) as client:
        assert client.get("/workspace/chat").status_code == 404
        assert client.get("/workspace/risk").status_code == 404


def test_customer_service_uses_versioned_isolated_visual_layer(app_pair):
    _, customer_service_app = app_pair
    with TestClient(customer_service_app) as client:
        page = client.get("/workspace/chat")
        stylesheet = client.get("/static/service_workspace_v03.css")
        workspace_script = client.get("/static/service_workspace.js")

        assert stylesheet.status_code == 200
        assert workspace_script.status_code == 200
        assert stylesheet.headers["content-type"].startswith("text/css")
        assert "service_workspace_v03.css?v=20260902-2" in page.text
        assert '<meta name="ui-build" content="20260902-2">' in page.text
        assert 'const storageKey = "loreal.service.ui-build"' in page.text
        assert 'window.addEventListener("pageshow"' in page.text
        assert "event.persisted" in page.text
        assert "window.location.reload()" in page.text
        assert "实时接待" not in page.text
        assert "订单台账" not in page.text
        assert "工单中心" not in page.text
        assert "商品档案</small>" not in page.text
        assert "service_workspace.js?v=20260902-2" in page.text
        assert 'href="/workspace/chat?ui=20260902-2"' in page.text
        assert 'href="/workspace/orders?ui=20260902-2"' in page.text
        assert 'href="/workspace/risk?ui=20260902-2"' in page.text
        assert 'const UI_BUILD = "20260902-2"' in workspace_script.text
        assert 'url.searchParams.set("ui", UI_BUILD)' in workspace_script.text
        assert '<span class="eyebrow">会话</span><h1>会话队列</h1>' not in page.text
        assert '<span class="eyebrow">订单业务</span><h1>订单管理</h1>' not in page.text
        assert '<span class="eyebrow">售后中心</span><h1>售后管理</h1>' not in page.text
        assert '<span class="eyebrow">商品目录</span><h1>商品管理</h1>' not in page.text
        assert 'from "./api.js?v=20260902-2"' in workspace_script.text
        assert "L'Oréal Service Atelier v0.3" in stylesheet.text
        assert "font-family: var(--brand-display)" in stylesheet.text
        assert "font-family: var(--brand-mono)" in stylesheet.text
        assert "--service-font: var(--body)" in stylesheet.text
        assert "--priority-label-size: 13px" in stylesheet.text
        assert "--display: var(--service-font)" in stylesheet.text
        assert "--mono: var(--service-font)" in stylesheet.text
        assert "font-family: var(--service-font)" in stylesheet.text
        assert stylesheet.text.count("font-size: var(--priority-label-size)") >= 5
        assert "font-size: var(--section-label-size)" in stylesheet.text
        assert ".service-v03 .atelier-masthead" in stylesheet.text
        assert ".service-v03 .chat-workspace" in stylesheet.text
        assert ".service-v03 .context-label" in stylesheet.text
        assert ".service-v03 .assistance-degraded-note" in stylesheet.text
        assert ".service-v03 .assistance-analysis-grid" in stylesheet.text
        assert ".service-v03 .assistance-glance" in stylesheet.text
        assert ".service-v03 .context-facts" in stylesheet.text
        assert ".service-v03 .assistance-reply" in stylesheet.text
        assert "overflow-y: scroll; scrollbar-gutter: stable" in stylesheet.text
        assert "grid-template-columns: 270px minmax(380px, 1fr) 450px" in stylesheet.text
        assert "font-size: var(--evidence-copy-size); line-height: 1.55" in stylesheet.text
        assert "background: #fffafb" in stylesheet.text
        assert "font-size: 14px; line-height: 1.7" in stylesheet.text
        assert "font-size: 14px; line-height: 1.7" in stylesheet.text
        assert "font-size: 13px" in stylesheet.text
        assert "scrollbar-color: var(--petal-mauve) var(--porcelain-bright)" in stylesheet.text
        assert ".service-v03 .context-rail::-webkit-scrollbar-thumb" in stylesheet.text
        assert ".service-v03 .context-sections::-webkit-scrollbar-thumb" in stylesheet.text
        assert "grid-template-columns: minmax(0, 1fr); grid-template-rows" in stylesheet.text
        assert "function markAssistanceStale()" in workspace_script.text
        assert "api.customerInsight(conversationId)" in workspace_script.text
        assert "void runAssistance()" in workspace_script.text
        assert "依据完整聊天" in workspace_script.text
        assert "未配置话术资料，由模型独立判断" in workspace_script.text
        assert "客户意图" in workspace_script.text
        assert "客服处理" in workspace_script.text
        assert "当前进度" in workspace_script.text
        assert (
            ".service-v03 .context-rail::-webkit-scrollbar-button:vertical:decrement"
            in stylesheet.text
        )
        assert (
            ".service-v03 .context-rail::-webkit-scrollbar-button:vertical:increment"
            in stylesheet.text
        )


def test_customer_service_shell_preserves_workspace_dom_contract(app_pair):
    _, customer_service_app = app_pair
    with TestClient(customer_service_app) as client:
        page = client.get("/workspace/chat").text

    required_tokens = (
        'class="service-page service-v03"',
        'id="workspaceNavigation"',
        'id="mobileNavScrim"',
        'data-workspace-view="chat"',
        'data-workspace-view="orders"',
        'data-workspace-view="after-sales"',
        'data-workspace-view="products"',
        'data-workspace-view="risk"',
        'id="serviceConversationList"',
        'id="serviceMessages"',
        'id="customerContextCard"',
        'id="customerPanorama"',
        'id="customerTrajectory"',
        'id="assistanceCard"',
        'id="assistanceGlance"',
        'id="assistanceReplyPreview"',
        'id="runAssistance"',
        'id="contextFacts"',
        "关联事实",
        'id="orderContextCard"',
        'id="workOrderContextCard"',
        'id="productContextCard"',
        'id="recordDrawer"',
        'id="importDialog"',
        'id="ticketDialog"',
    )
    for token in required_tokens:
        assert token in page
    assert "客户要什么" not in page
    assert "客服做了什么" not in page
    assert "现在到哪了" not in page
    assert 'id="assistanceTitle"' not in page
    assert 'class="assistance-mark"' not in page
    assert "AI 会话判断 · 生成内容" not in page
    assert 'id="assistanceMode"' not in page
    assert "先看结论" not in page
    assert page.index('id="assistanceReplyPreview"') < page.index('id="openAssistance"')


def test_customer_panorama_is_independent_and_preserves_assistance_contract(app_pair):
    _, customer_service_app = app_pair
    with TestClient(customer_service_app) as client:
        page = client.get("/workspace/chat").text
        workspace_script = client.get("/static/service_workspace.js").text
        api_script = client.get("/static/api.js").text

    assert page.index('id="customerPanorama"') < page.index(
        'id="customerTrajectory"'
    ) < page.index('id="assistanceCard"')
    for token in (
        'id="panoramaIdentity"',
        'id="panoramaCustomerId"',
        'id="panoramaRegion"',
        'id="panoramaPaidAmount"',
        'id="panoramaRisk"',
        'id="panoramaTags"',
        'id="panoramaOrderCount"',
        'id="panoramaAverageOrder"',
        'id="panoramaConsultationCount"',
        'id="panoramaAfterSalesCount"',
        'id="panoramaTrajectoryCount"',
        'id="panoramaAvatar"',
        'id="openCustomerProfile"',
        'id="retryCustomerPanorama"',
    ):
        assert token in page

    assert "customerPanorama: (id)" in api_script
    assert "/api/v1/management/conversations/${encodeURIComponent(id)}/panorama" in api_script
    assert "panoramaGeneration: 0" in workspace_script
    assert "function startCustomerPanorama(conversationId)" in workspace_script
    assert workspace_script.count("++state.panoramaGeneration") == 1
    assert "api.customerPanorama(conversationId)" in workspace_script
    assert "journey_insights" in workspace_script
    assert '<i aria-hidden="true"></i>' not in workspace_script
    stale_guard = (
        "state.conversationId !== conversationId || "
        "generation !== state.panoramaGeneration"
    )
    assert workspace_script.count(stale_guard) == 2
    assert 'data-state="unselected"' in page
    assert 'dataset.state = "loading"' in workspace_script
    assert 'dataset.state = isPartial ? "partial" : "ready"' in workspace_script
    assert 'dataset.state = "error"' in workspace_script
    assert "用户档案 · 精确客户聚合" in workspace_script
    assert '$("#retryCustomerPanorama").addEventListener("click"' in workspace_script

    load_start = workspace_script.index("startCustomerPanorama(conversation.id)")
    promise_start = workspace_script.index("const [messages, context] = await Promise.all([")
    promise_end = workspace_script.index("]);", promise_start)
    assert load_start < promise_start
    assert "customerPanorama" not in workspace_script[promise_start:promise_end]
    assert "customerInsight: (id)" in api_script
    assert "/panorama/analysis" in api_script
    assert workspace_script.count("api.customerInsight(conversationId)") == 1
    assert "api.conversationAssistance(conversationId)" not in workspace_script
    for token in (
        'id="assistanceModeChip"',
        'id="assistanceInsight"',
        'id="assistanceIntent"',
        'id="assistanceConfidence"',
        'id="assistanceConfidenceTrack"',
    ):
        assert token in page
    assert page.index('id="customerTrajectory"') < page.index(
        'id="assistanceInsight"'
    ) < page.index('id="assistanceReplyPreview"')
    assert "insight.assistance" in workspace_script
    assert 'insight.mode === "online" ? "在线模型" : "离线分析"' in workspace_script

    assistance_start = page.index('            <section class="assistance-card"')
    assistance_end = page.index(
        '            <details class="context-facts"', assistance_start
    )
    assistance_markup = page[assistance_start:assistance_end]
    assert "AI 分析" in assistance_markup
    assert "用户意图" in assistance_markup
    assert "情绪判断" not in assistance_markup
    assert "建议回复 · 发送前请确认" in assistance_markup

    function_start = workspace_script.index("function resetAssistance()")
    function_end = workspace_script.index("function conversationRow(", function_start)
    assistance_functions = workspace_script[function_start:function_end]
    assert assistance_functions.count("api.customerInsight(conversationId)") == 1
    assert "showAssistanceDetails" in assistance_functions
    assert "useAssistanceReply" in assistance_functions
    assert "markAssistanceStale" in assistance_functions


def test_risk_workspace_has_independent_functional_data_flow(app_pair):
    _, customer_service_app = app_pair
    with TestClient(customer_service_app) as client:
        page = client.get("/workspace/risk").text
        workspace_script = client.get("/static/service_workspace.js").text
        api_script = client.get("/static/api.js").text
        workspace_css = client.get("/static/service_workspace_v03.css").text

    for token in (
        'data-workspace-link="risk"',
        'data-workspace-view="risk"',
        'id="navRiskCount"',
        'id="riskOverviewState"',
        'id="riskMetrics"',
        'id="riskTrend"',
        'id="riskKindFilters"',
        'data-risk-kind="emotion_escalation"',
        'data-risk-kind="repeat_contact"',
        'data-risk-kind="repeat_refund"',
        'data-risk-kind="public_complaint"',
        'data-risk-kind="service_timeout"',
        'id="riskTotal"',
        'id="riskTableBody"',
        'id="riskPagination"',
        'id="riskPrevPage"',
        'id="riskNextPage"',
        'href="/workspace/chat?ui=20260902-2"',
    ):
        assert token in page

    assert 'aria-pressed="true"' in page
    assert 'aria-pressed="false"' in page
    assert "riskOverview: (params = {})" in api_script
    assert "riskWarnings: (params = {})" in api_script
    assert "riskWarning: (id)" in api_script
    assert "/api/v1/management/risks/overview" in api_script
    assert "/api/v1/management/risks${queryString(params)}" in api_script
    assert "/api/v1/management/risks/${encodeURIComponent(id)}" in api_script

    for token in (
        "function loadRiskOverview()",
        "function loadRiskWarnings()",
        "function openRiskWarning(id)",
        "void loadRiskOverview()",
        "void loadRiskWarnings()",
        "api.riskOverview()",
        "api.riskWarnings({",
        "api.riskWarning(id)",
        'id="riskOverviewRetry"',
        "renderTableError($(\"#riskTableBody\"), 7, error, loadRiskWarnings)",
        'item.setAttribute("aria-pressed", String(isActive))',
        'data-risk-detail="${escapeHtml(risk.id)}"',
        "riskListGeneration: 0",
        "const generation = ++state.riskListGeneration",
        "generation !== state.riskListGeneration",
        'openDrawer(`',
        '"risk", id',
        "返回相关会话",
    ):
        assert token in workspace_script

    assert "result.warning_count" in workspace_script
    assert "result.high_open_count" in workspace_script
    assert "result.average_resolution_hours" in workspace_script
    assert "result.closure_rate" in workspace_script
    assert "Promise.all([loadRiskOverview" not in workspace_script
    trend_a11y = (
        'role="img" aria-label="${escapeHtml(point.date)}，'
        '${point.warning_count} 条预警"'
    )
    assert trend_a11y in workspace_script
    assert ".risk-workspace:not([hidden])" in workspace_css
    assert ".risk-table tbody tr { cursor: default; }" in workspace_css
    assert ".customer-panorama::before" in workspace_css
    assert ".context-body > :first-child { min-height: 0; }" in workspace_css
    assert "@media (prefers-reduced-motion: reduce)" in workspace_css
    assert 'id="assistanceCard"' in page
    assert page.count('id="assistanceCard"') == 1


def test_frontends_localize_operational_labels_and_work_order_fields(app_pair):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_service_app) as client:
        service_page = client.get("/workspace/after-sales").text
        service_script = client.get("/static/service_workspace.js").text
        chat_script = client.get("/static/chat.js").text
    with TestClient(customer_app) as client:
        customer_page = client.get("/").text
        customer_script = client.get("/static/customer.js").text

    assert "service_workspace.js?v=20260902-2" in service_page
    assert "customer.js?v=20260810-2" in customer_page
    assert 'from "./chat.js?v=20260810-1"' in service_script
    assert 'from "./chat.js?v=20260810-1"' in customer_script
    assert 'customer_service: "客服"' in chat_script
    assert 'customer: "客户"' in chat_script
    assert "export function messageTypeLabel" in chat_script
    assert 'key.replaceAll("_", " ")' not in service_script

    field_labels = {
        "issue_kind": "问题类型",
        "product_external_id": "商品货号",
        "product_name": "商品名称",
        "quantity": "数量",
        "original_tracking_no": "原订单物流单号",
        "replacement_tracking_no": "补发物流单号",
        "logistics_company": "快递公司",
        "warehouse": "发货仓库",
        "is_urgent": "是否加急",
        "payment_type": "打款类型",
        "reason": "原因",
        "amount": "金额（元）",
        "masked_real_name": "支付宝实名（脱敏）",
        "masked_account": "支付宝账号（脱敏）",
        "related_tracking_no": "相关物流单号",
        "transfer_status": "转账状态",
        "tracking_no": "物流单号",
        "order_amount": "订单实付金额（元）",
        "handling_plan": "处理方案",
        "province": "收货省",
        "city": "收货市",
        "channel": "登记类型",
        "age": "年龄",
        "skin_type": "肤质",
        "product_batch_no": "产品批次号",
        "affected_area": "不适部位",
        "symptoms": "症状描述",
        "onset_after": "使用后多久出现",
        "stopped_use": "是否停用",
        "sought_medical_care": "是否就医",
        "package_type": "包裹类型",
        "return_tracking_no": "退货物流单号",
        "refund_external_id": "退款编号",
        "receipt_advice": "签收建议",
        "is_abnormal": "是否异常",
    }
    for key, label in field_labels.items():
        assert f'{key}: "{label}"' in service_script

    for operational_english in (
        "AFTER-SALES DETAIL",
        "ORDER DETAIL",
        "PRODUCT DETAIL",
        "WORKBOOK IMPORT",
        "CREATE AFTER-SALES",
        "SELECT A CONVERSATION",
    ):
        assert operational_english not in service_page
        assert operational_english not in service_script

    assert "例如 shipped" not in customer_page


def test_customer_product_list_has_accessible_collapse_control(app_pair):
    customer_app, _ = app_pair
    with TestClient(customer_app) as client:
        page = client.get("/").text
        script = client.get("/static/customer.js").text
        stylesheet = client.get("/static/styles.css").text

    assert "styles.css?v=20260901-6" in page
    assert "customer.js?v=20260810-2" in page
    assert 'id="customerProductListToggle"' in page
    assert 'aria-controls="customerProductList"' in page
    assert 'aria-expanded="true"' in page
    assert "收起商品列表" in page
    assert "setProductListExpanded" in script
    assert 'elements.productListToggle.addEventListener("click"' in script
    assert "await loadProducts(query);" in script
    assert "setProductListExpanded(true);" in script
    assert ".customer-product-list" in stylesheet
    assert ".customer-page" in stylesheet
    assert "--priority-label-size: 13px" in stylesheet
    assert "--display: var(--body)" in stylesheet
    assert "--mono: var(--body)" in stylesheet
    assert ".customer-page .brand-name" in stylesheet
    assert ".customer-page .brand-subtitle" in stylesheet
    assert stylesheet.count("font-size: var(--priority-label-size)") >= 3
    assert "overflow-y: auto" in stylesheet
    assert "grid-auto-rows: max-content" in stylesheet
    assert ".customer-product-list .data-card h3" in stylesheet
    assert "place-items: center" in stylesheet
    assert "overflow-wrap: anywhere" in stylesheet
    assert "scrollbar-color: var(--petal-mauve) var(--porcelain-bright)" in stylesheet
    assert ".customer-product-list::-webkit-scrollbar-thumb" in stylesheet
    assert ".customer-product-list::-webkit-scrollbar-button:vertical:decrement" in stylesheet
    assert ".customer-product-list::-webkit-scrollbar-button:vertical:increment" in stylesheet


def test_customer_and_service_share_atelier_visual_contract(app_pair):
    customer_app, customer_service_app = app_pair
    with TestClient(customer_app) as customer:
        customer_page = customer.get("/").text
        shared_css = customer.get("/static/styles.css").text
    with TestClient(customer_service_app) as service:
        service_page = service.get("/workspace/chat").text
        service_css = service.get("/static/service_workspace_v03.css").text

    assert "styles.css?v=20260901-6" in customer_page
    assert "styles.css?v=20260901-6" in service_page
    assert "service_workspace_v03.css?v=20260902-2" in service_page
    assert service_page.index("styles.css?v=20260901-6") < service_page.index(
        "service_workspace_v03.css?v=20260902-2"
    )

    assert "grid-template-columns: 270px minmax(380px, 1fr) 410px" in shared_css
    assert "grid-template-columns: 250px minmax(360px, 1fr) 370px" in shared_css
    assert "font-size: 16px" in service_css
    assert "background: var(--porcelain)" in service_css

    for token in (
        "--masthead-height-desktop: 88px",
        "--masthead-height-tablet: 76px",
        "--masthead-height-mobile: 68px",
        "--masthead-surface: rgb(249 245 248 / 86%)",
        "--masthead-blur: 24px",
        "--panel-surface: rgb(255 250 251 / 82%)",
        "--panel-highlight: rgb(255 255 255 / 72%)",
        "--control-standard: 40px",
        "--control-compact: 34px",
        "--evidence-copy-size: 17px",
    ):
        assert token in shared_css

    assert "grid-template-rows: var(--masthead-height-desktop) minmax(0, 1fr)" in shared_css
    assert "background: var(--masthead-surface)" in shared_css
    assert "backdrop-filter: blur(var(--masthead-blur))" in shared_css
    assert "background: var(--panel-surface)" in shared_css
    assert "border: 1px solid var(--panel-highlight)" in shared_css
    assert ".spectrum-rail::after" in shared_css
    assert "repeating-linear-gradient" in shared_css
    assert "pointer-events: none" in shared_css

    assert "--service-header: var(--masthead-height-desktop)" in service_css
    assert "height: var(--service-header)" in service_css
    assert "background: var(--masthead-surface)" in service_css
    assert "background: var(--panel-surface)" in service_css
    assert "border: 1px solid var(--panel-highlight)" in service_css
    assert "font-family: var(--brand-display)" in shared_css
    assert "font-family: var(--brand-mono)" in shared_css
    assert "font-family: var(--brand-display)" in service_css
    assert "font-family: var(--brand-mono)" in service_css
