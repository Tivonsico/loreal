import { api, ConversationSocket } from "./api.js?v=20260903-4";
import {
  MessageTimeline,
  autoGrow,
  formatDate,
  formatMoney,
  messageTypeLabel,
  messageTypeForFile,
  orderStatusLabel,
  setConnectionState,
  showToast,
} from "./chat.js?v=20260810-1";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const UI_BUILD = "20260903-4";
const viewNames = {
  chat: ["客户沟通", "客服接待席"],
  orders: ["订单管理", "订单业务"],
  "after-sales": ["售后管理", "售后中心"],
  products: ["商品管理", "商品目录"],
  risk: ["情绪风险", "预警看板"],
};
const ticketLabels = {
  replacement_exchange: "补发换货",
  offline_payment: "线下打款",
  logistics: "物流问题",
  adverse_reaction: "不良反应",
  after_sale_return: "售后退货",
};
const statusLabels = { pending: "待处理", processing: "处理中", completed: "已完成" };
const detailFieldLabels = {
  issue_kind: "问题类型",
  product_external_id: "商品货号",
  product_name: "商品名称",
  quantity: "数量",
  original_tracking_no: "原订单物流单号",
  replacement_tracking_no: "补发物流单号",
  logistics_company: "快递公司",
  warehouse: "发货仓库",
  is_urgent: "是否加急",
  payment_type: "打款类型",
  reason: "原因",
  amount: "金额（元）",
  masked_real_name: "支付宝实名（脱敏）",
  masked_account: "支付宝账号（脱敏）",
  related_tracking_no: "相关物流单号",
  transfer_status: "转账状态",
  tracking_no: "物流单号",
  order_amount: "订单实付金额（元）",
  handling_plan: "处理方案",
  province: "收货省",
  city: "收货市",
  channel: "登记类型",
  age: "年龄",
  skin_type: "肤质",
  product_batch_no: "产品批次号",
  affected_area: "不适部位",
  symptoms: "症状描述",
  onset_after: "使用后多久出现",
  stopped_use: "是否停用",
  sought_medical_care: "是否就医",
  package_type: "包裹类型",
  return_tracking_no: "退货物流单号",
  refund_external_id: "退款编号",
  receipt_advice: "签收建议",
  is_abnormal: "是否异常",
};

function activeView() {
  const section = window.location.pathname.split("/").filter(Boolean).at(-1);
  return viewNames[section] ? section : "chat";
}

const state = {
  view: activeView(),
  summary: null,
  conversationId: new URLSearchParams(window.location.search).get("conversation")
    || localStorage.getItem("beauty.service_conversation"),
  conversation: null,
  context: null,
  assistance: null,
  assistanceByConversation: new Map(),
  assistanceGeneration: 0,
  panorama: null,
  panoramaGeneration: 0,
  riskGeneration: 0,
  riskDetailGeneration: 0,
  riskType: "",
  selectedRiskConversation: null,
  riskPollTimer: null,
  conversations: [],
  ticketType: "",
  drawerTrigger: null,
};

const elements = {
  toasts: $("#serviceToasts"),
  drawer: $("#recordDrawer"),
  drawerContent: $("#drawerContent"),
  drawerScrim: $("#drawerScrim"),
  importDialog: $("#importDialog"),
  importPreview: $("#importPreview"),
  ticketDialog: $("#ticketDialog"),
  messages: $("#serviceMessages"),
  connection: $("#serviceConnectionStatus"),
  connectionText: $("#serviceConnectionText"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function errorMessage(error) {
  return error?.message || "请求没有完成，请稍后重试";
}

function badge(value, kind = "neutral") {
  return `<span class="status-badge is-${kind}">${escapeHtml(value || "—")}</span>`;
}

function statusBadge(status) {
  const kind = status === "completed" ? "success" : status === "pending" ? "warning" : "active";
  return badge(statusLabels[status] || status, kind);
}

function setUrlParam(key, value) {
  const url = new URL(window.location.href);
  if (value) url.searchParams.set(key, value);
  else url.searchParams.delete(key);
  window.history.replaceState({}, "", url);
}

function routeHref(view, params = {}) {
  const url = new URL(`/workspace/${view}`, window.location.origin);
  url.searchParams.set("ui", UI_BUILD);
  Object.entries(params).forEach(([key, value]) => {
    if (value) url.searchParams.set(key, value);
  });
  return `${url.pathname}${url.search}`;
}

function initializeShell() {
  $$('[data-workspace-view]').forEach((view) => {
    view.hidden = view.dataset.workspaceView !== state.view;
  });
  $$('[data-workspace-link]').forEach((link) => {
    const isActive = link.dataset.workspaceLink === state.view;
    link.classList.toggle("is-active", isActive);
    if (isActive) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("#workspaceTitle").textContent = viewNames[state.view][0];
  $("#workspaceEyebrow").textContent = viewNames[state.view][1];
  const formatter = new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
  $("#workspaceClock").textContent = formatter.format(new Date());
  $("#mobileNavToggle").addEventListener("click", () => setMobileNavigation(!document.body.classList.contains("nav-open")));
  $("#mobileNavScrim").addEventListener("click", () => setMobileNavigation(false));
}

function setMobileNavigation(isOpen) {
  const shouldRestoreFocus = !isOpen && ($("#workspaceNavigation").contains(document.activeElement) || document.activeElement === $("#mobileNavScrim"));
  document.body.classList.toggle("nav-open", isOpen);
  $("#mobileNavToggle").setAttribute("aria-expanded", String(isOpen));
  $("#mobileNavToggle").setAttribute("aria-label", isOpen ? "关闭工作区导航" : "打开工作区导航");
  $("#mobileNavScrim").hidden = !isOpen;
  if (isOpen) $('[data-workspace-link].is-active')?.focus();
  else if (shouldRestoreFocus) $("#mobileNavToggle").focus();
}

async function loadSummary() {
  try {
    state.summary = await api.managementSummary();
    $("#navPendingCount").textContent = state.summary.pending_work_orders;
    renderMetrics();
  } catch (error) {
    $("#navPendingCount").textContent = "!";
    $("#navPendingCount").title = "概览暂时不可用";
    showToast(elements.toasts, errorMessage(error), "error");
  }
}

function metric(label, value, note) {
  return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`;
}

function renderMetrics() {
  if (!state.summary) return;
  if ($("#orderMetrics")) {
    $("#orderMetrics").innerHTML = [
      metric("全部订单", state.summary.orders, "已同步业务订单"),
      metric("关联售后", state.summary.work_orders, "可跳转至售后中心"),
      metric("商品档案", state.summary.products, "来自订单商品货号"),
    ].join("");
  }
  if ($("#ticketMetrics")) {
    $("#ticketMetrics").innerHTML = [
      metric("全部工单", state.summary.work_orders, "五类售后统一管理"),
      metric("待跟进", state.summary.pending_work_orders, "待处理与处理中"),
      metric("涉及会话", state.summary.conversations, "可回到原始聊天"),
    ].join("");
  }
  if ($("#productMetrics")) {
    $("#productMetrics").innerHTML = [
      metric("商品数量", state.summary.products, "已建立商品档案"),
      metric("订单覆盖", state.summary.orders, "订单可反查商品"),
      metric("数据来源", "Excel + API", "统一真实数据源"),
    ].join("");
  }
}

const timeline = elements.messages ? new MessageTimeline(elements.messages, "customer_service") : null;
const socket = new ConversationSocket({
  onState: (value) => {
    if (elements.connection) setConnectionState(elements.connection, elements.connectionText, value);
  },
  onMessage: (message) => {
    if (message.conversation_id === state.conversationId) {
      timeline?.add(message);
      markAssistanceStale();
    }
  },
});

function resetAssistance() {
  state.assistance = null;
  state.assistanceGeneration += 1;
  $("#assistanceCard").dataset.state = "idle";
  $("#assistanceSummary").textContent = state.conversationId
    ? "会结合完整聊天和关联业务信息生成结论。"
    : "选中会话后会自动分析，不会自动发送回复。";
  $("#assistanceGlance").hidden = true;
  $("#assistanceReplyPreview").hidden = true;
  $("#runAssistance").textContent = "重新分析";
  $("#runAssistance").disabled = !state.conversationId;
  $("#runAssistance").hidden = false;
  $("#openAssistance").hidden = true;
  $("#aiInsightCard").dataset.state = "idle";
  $("#aiInsightIntent").textContent = "待分析";
  $("#aiInsightEmotion").textContent = "待分析";
  $("#aiIntentConfidence").textContent = "0%";
  $("#aiEmotionConfidence").textContent = "0%";
  $("#aiIntentBar").style.width = "0%";
  $("#aiEmotionBar").style.width = "0%";
  $("#aiInsightStatus").textContent = state.conversationId ? "正在等待分析" : "选择会话后自动分析";
}

function markAssistanceStale() {
  if (!state.assistance) return;
  $("#assistanceCard").dataset.state = "stale";
  $("#assistanceSummary").textContent = "这份建议早于最新消息，请重新核验后再使用。";
  $("#assistanceGlance").hidden = true;
  $("#assistanceReplyPreview").hidden = true;
  $("#runAssistance").textContent = "重新分析";
  $("#aiInsightCard").dataset.state = "stale";
  $("#aiInsightStatus").textContent = "有新消息，需重新分析";
}

const emotionLabels = {
  positive: "积极", neutral: "平稳", anxious: "焦虑", angry: "愤怒", sad: "低落",
};

function renderAiInsight(result) {
  const confidence = Math.round((result.emotion_confidence ?? 0.5) * 100);
  const intentConfidence = Math.round((result.intent_confidence ?? 0.5) * 100);
  $("#aiInsightCard").dataset.state = result.degraded_reason ? "degraded" : "ready";
  $("#aiInsightIntent").textContent = result.intent || "一般咨询";
  $("#aiInsightEmotion").textContent = emotionLabels[result.emotion] || "平稳";
  $("#aiIntentConfidence").textContent = `${intentConfidence}%`;
  $("#aiEmotionConfidence").textContent = `${confidence}%`;
  $("#aiIntentBar").style.width = `${intentConfidence}%`;
  $("#aiEmotionBar").style.width = `${confidence}%`;
  $("#aiInsightStatus").textContent = result.degraded_reason ? "已使用快速离线判断" : "已分析完整聊天";
}

function assistanceStatusLabel(status) {
  return {
    present: "已核验",
    not_linked: "未关联",
    referenced_not_found: "引用未找到",
    conflict: "需要人工核对",
    filtered: "已安全过滤",
    source_unavailable: "资料未配置",
  }[status] || status;
}

function showAssistanceDetails() {
  if (!state.assistance) return;
  const result = state.assistance;
  const facts = result.facts.map((fact) => `<li data-status="${escapeHtml(fact.status)}"><span>${escapeHtml(fact.label)}</span><strong>${escapeHtml(assistanceStatusLabel(fact.status))}</strong><small>${escapeHtml(fact.summary)}</small></li>`).join("");
  const risks = result.risks.map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>未发现需要额外提示的风险</li>";
  const actions = result.next_actions.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const degraded = result.degraded_reason
    ? `<p class="assistance-degraded-note"><strong>在线分析未完成</strong>${escapeHtml(result.degraded_reason)}</p>`
    : "";
  openDrawer(`<span class="eyebrow">接待辅助 · ${result.mode === "offline" ? "完整会话离线分析" : "在线模型分析"}</span><h2>会话判断</h2>${degraded}<p class="drawer-lead">${escapeHtml(result.summary)}</p><div class="assistance-analysis-grid"><section><span>客户意图</span><p>${escapeHtml(result.intent)}</p></section><section><span>客服处理</span><p>${escapeHtml(result.service_handling)}</p></section><section><span>当前进度</span><p>${escapeHtml(result.current_status)}</p></section></div><h3 class="drawer-section-title">事实核验</h3><ul class="verification-list">${facts}</ul><h3 class="drawer-section-title">需要留意</h3><ul class="assistance-copy-list">${risks}</ul><h3 class="drawer-section-title">建议下一步</h3><ol class="assistance-copy-list">${actions}</ol><div class="reply-draft"><span>建议回复 · 发送前请人工确认</span><p>${escapeHtml(result.suggested_reply)}</p><button class="button button-primary button-full" id="useAssistanceReply" type="button">放入回复框</button></div><p class="assistance-watermark">依据完整聊天 ${result.basis_message_count} 条 · 水位 #${escapeHtml(result.basis_last_message_id || "空")} · ${result.playbook_status === "source_unavailable" ? "未配置话术资料，由模型独立判断" : "已参考话术资料"}</p>`, "assistant", state.conversationId);
  $("#useAssistanceReply").addEventListener("click", () => useAssistanceReply(result, true));
}

function useAssistanceReply(result, closeDetails = false) {
  const input = $("#serviceMessage");
  input.value = result.suggested_reply;
  autoGrow(input);
  if (closeDetails) closeDrawer();
  input.focus();
}

function renderAssistance(result) {
  const card = $("#assistanceCard");
  state.assistance = result;
  renderAiInsight(result);
  if (state.panorama) renderPanorama(state.panorama);
  card.dataset.state = "ready";
  $("#assistanceSummary").textContent = result.summary;
  $("#assistanceIntent").textContent = result.intent;
  $("#assistanceHandling").textContent = result.service_handling;
  $("#assistanceProgress").textContent = result.current_status;
  $("#assistanceGlance").hidden = false;
  $("#assistanceReply").textContent = result.suggested_reply;
  $("#assistanceReplyPreview").hidden = false;
  $("#runAssistance").textContent = "重新分析";
  $("#runAssistance").hidden = false;
  $("#runAssistance").disabled = false;
  $("#openAssistance").hidden = false;
}

function restoreOrRunAssistance(messages) {
  const cached = state.assistanceByConversation.get(state.conversationId);
  if (!cached) {
    void runAssistance();
    return;
  }
  renderAssistance(cached);
  const latestMessageId = messages.at(-1)?.id ?? null;
  if (String(cached.basis_last_message_id ?? "") !== String(latestMessageId ?? "")) {
    markAssistanceStale();
  }
}

async function runAssistance() {
  if (!state.conversationId) return;
  const conversationId = state.conversationId;
  const previous = state.assistanceByConversation.get(conversationId) || null;
  const generation = ++state.assistanceGeneration;
  const card = $("#assistanceCard");
  card.dataset.state = "loading";
  $("#aiInsightCard").dataset.state = "loading";
  $("#aiInsightStatus").textContent = "正在快速分析…";
  $("#assistanceSummary").textContent = "正在读完整聊天，并核对订单、商品和售后…";
  $("#assistanceGlance").hidden = true;
  $("#assistanceReplyPreview").hidden = true;
  $("#runAssistance").disabled = true;
  $("#runAssistance").hidden = true;
  $("#openAssistance").hidden = true;
  try {
    const result = await api.conversationAssistance(conversationId);
    if (state.conversationId !== conversationId || generation !== state.assistanceGeneration) return;
    state.assistanceByConversation.set(conversationId, result);
    renderAssistance(result);
  } catch (error) {
    if (state.conversationId !== conversationId || generation !== state.assistanceGeneration) return;
    if (previous) {
      renderAssistance(previous);
      markAssistanceStale();
      $("#aiInsightStatus").textContent = "重新分析失败，保留上次结果";
      $("#assistanceSummary").textContent = `${errorMessage(error)}。已保留上次分析，请核验后使用。`;
    } else {
      state.assistance = null;
      $("#aiInsightCard").dataset.state = "error";
      $("#aiInsightStatus").textContent = "分析暂时不可用";
      card.dataset.state = "error";
      $("#assistanceSummary").textContent = `${errorMessage(error)}。聊天与业务信息仍可正常使用。`;
    }
    $("#runAssistance").textContent = "重新尝试";
    $("#runAssistance").hidden = false;
  } finally {
    if (state.conversationId === conversationId && generation === state.assistanceGeneration) {
      $("#runAssistance").disabled = false;
    }
  }
}

function conversationRow(conversation) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "conversation-item enriched-conversation";
  button.dataset.conversationId = conversation.id;
  button.classList.toggle("is-active", conversation.id === state.conversationId);
  button.innerHTML = `
    <span class="conversation-title">${escapeHtml(conversation.buyer_nickname || conversation.title || "未命名会话")}</span>
    <span class="conversation-meta"><span>${escapeHtml(conversation.source_external_id || conversation.id)}</span><time>${formatDate(conversation.updated_at)}</time></span>
    <span class="conversation-relations">${conversation.order_external_id ? badge(`订单 ${conversation.order_external_id}`) : ""}${conversation.work_order_type ? badge(ticketLabels[conversation.work_order_type], conversation.work_order_status === "completed" ? "success" : "warning") : ""}</span>`;
  button.addEventListener("click", () => selectConversation(conversation));
  return button;
}

async function loadConversations() {
  const params = Object.fromEntries(new FormData($("#conversationFilter")));
  params.page_size = 200;
  try {
    const result = await api.managementConversations(params);
    state.conversations = result.items;
    $("#conversationCount").textContent = result.total;
    const list = $("#serviceConversationList");
    list.replaceChildren();
    result.items.forEach((item) => list.append(conversationRow(item)));
    if (!result.items.length) list.innerHTML = '<div class="empty-compact">当前条件下没有会话</div>';
    if (state.conversationId && !state.conversation) {
      const remembered = result.items.find((item) => item.id === state.conversationId);
      if (remembered) await selectConversation(remembered);
    }
  } catch (error) {
    $("#serviceConversationList").innerHTML = `<div class="empty-compact">${escapeHtml(errorMessage(error))}<br>调整条件或稍后重新筛选</div>`;
    showToast(elements.toasts, errorMessage(error), "error");
  }
}

function setContextLoading() {
  ["customerContextCard", "orderContextCard", "workOrderContextCard", "productContextCard"].forEach((id) => {
    const label = $("#" + id).querySelector(".context-label")?.textContent || "信息";
    $("#" + id).innerHTML = `<span class="context-label">${escapeHtml(label)}</span><div class="context-empty">正在读取…</div>`;
  });
  $("#contextFacts").open = false;
  $("#contextFactsSummary").textContent = "正在读取关联信息…";
  $("#createTicketFromChat").disabled = true;
  state.panorama = null;
  $("#customerPanorama").dataset.state = "loading";
  $("#panoramaName").textContent = "正在读取…";
  $("#panoramaTags").replaceChildren();
  $("#serviceTrailList").innerHTML = '<p class="compact-placeholder">正在还原服务轨迹…</p>';
}

function renderServiceTrail(nodes = [], aiSummaries = []) {
  $("#serviceTrailCount").textContent = `${nodes.length} 个节点`;
  $("#serviceTrailList").innerHTML = nodes.map((node, index) => `
    <article><i aria-hidden="true"></i><div><time>${escapeHtml(formatDate(node.occurred_at))}</time>
    <strong>${escapeHtml(node.title)}</strong><p>${escapeHtml(aiSummaries[index] || node.detail || "已记录")}</p></div></article>`).join("")
    || '<p class="compact-placeholder">暂无可还原的服务节点</p>';
}

function renderPanorama(panorama) {
  state.panorama = panorama;
  $("#customerPanorama").dataset.state = "ready";
  const name = panorama.buyer_nickname || panorama.customer_id;
  $("#panoramaAvatar").textContent = name.slice(0, 1);
  $("#panoramaName").textContent = name;
  $("#panoramaRegion").textContent = panorama.region || "地域未记录";
  $("#panoramaRisk").textContent = "数据已核验";
  $("#panoramaSpend").textContent = formatMoney(panorama.recorded_paid_amount);
  $("#panoramaOrders").textContent = `${panorama.order_count} 单`;
  $("#panoramaConsultations").textContent = `${panorama.consultation_count_30d} 次`;
  $("#panoramaAfterSales").textContent = `${panorama.after_sales_count} 单`;
  const tags = [...(panorama.fact_tags || []), ...(state.assistance?.customer_tags || [])].slice(0, 4);
  $("#panoramaTags").innerHTML = tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("");
  renderServiceTrail(panorama.service_trail, state.assistance?.trail_summaries || []);
}

async function loadCustomerPanorama(conversationId) {
  const generation = ++state.panoramaGeneration;
  try {
    const panorama = await api.customerPanorama(conversationId);
    if (state.conversationId !== conversationId || generation !== state.panoramaGeneration) return;
    renderPanorama(panorama);
  } catch (error) {
    if (state.conversationId !== conversationId || generation !== state.panoramaGeneration) return;
    $("#customerPanorama").dataset.state = "error";
    $("#panoramaName").textContent = "全景暂时不可用";
    $("#serviceTrailList").innerHTML = `<p class="compact-placeholder">${escapeHtml(errorMessage(error))}</p>`;
  }
}

async function selectConversation(conversation) {
  state.conversation = conversation;
  state.conversationId = conversation.id;
  localStorage.setItem("beauty.service_conversation", conversation.id);
  setUrlParam("conversation", conversation.id);
  $("#serviceChatEmpty").hidden = true;
  $("#serviceChatView").hidden = false;
  $("#serviceChatMeta").textContent = `客户 · ${conversation.buyer_nickname || conversation.customer_id}`;
  $("#serviceChatTitle").textContent = conversation.title || "客户咨询";
  $("#serviceCustomerId").textContent = conversation.buyer_nickname || conversation.customer_id;
  $("#serviceConversationId").textContent = conversation.source_external_id || conversation.id;
  $("#serviceMessages").innerHTML = '<div class="empty-compact">正在读取消息…</div>';
  setContextLoading();
  resetAssistance();
  void loadCustomerPanorama(conversation.id);
  $$(".conversation-item").forEach((item) => item.classList.toggle("is-active", item.dataset.conversationId === conversation.id));
  try {
    const [messages, context] = await Promise.all([
      api.listMessages(conversation.id, { limit: 200 }),
      api.conversationContext(conversation.id),
    ]);
    if (state.conversationId !== conversation.id) return;
    timeline.reset(messages.items);
    state.context = context;
    renderContext(context);
    socket.connect(conversation.id);
    restoreOrRunAssistance(messages.items);
  } catch (error) {
    timeline.reset([]);
    $("#customerContextCard").innerHTML = `<span class="context-label">客户</span><div class="context-empty">${escapeHtml(errorMessage(error))}</div>`;
    showToast(elements.toasts, errorMessage(error), "error");
  }
}

function contextLink(view, id, label) {
  return `<a class="context-link" href="${routeHref(view, { [view === "after-sales" ? "ticket" : view.slice(0, -1)]: id, return_conversation: state.conversationId })}">${escapeHtml(label)} <span>→</span></a>`;
}

function renderContext(context) {
  const customer = context.conversation;
  $("#customerContextCard").innerHTML = `<span class="context-label">客户</span><h3>${escapeHtml(customer.buyer_nickname || customer.customer_id)}</h3><p>会话 ${escapeHtml(customer.source_external_id || customer.id)}</p>${badge(customer.status === "open" ? "沟通中" : customer.status, "active")}`;
  if (context.product) {
    $("#productContextCard").innerHTML = `<span class="context-label">商品</span><h3>${escapeHtml(context.product.name)}</h3><p>${escapeHtml(context.product.external_id)} · ${formatMoney(context.product.price)}</p>${contextLink("products", context.product.external_id, "查看商品档案")}`;
  } else $("#productContextCard").innerHTML = '<span class="context-label">商品</span><div class="context-empty">暂无关联商品</div>';
  if (context.order) {
    $("#orderContextCard").innerHTML = `<span class="context-label">订单</span><h3>${escapeHtml(context.order.external_id)}</h3><p>${escapeHtml(context.order.product_name || "未填写商品")} · ${formatMoney(context.order.total_amount)}</p>${badge(orderStatusLabel(context.order.status), "active")}${contextLink("orders", context.order.external_id, "查看订单详情")}`;
  } else $("#orderContextCard").innerHTML = '<span class="context-label">订单</span><div class="context-empty">暂无关联订单</div>';
  const createButton = $("#createTicketFromChat");
  if (context.work_order) {
    const ticket = context.work_order;
    $("#workOrderContextCard").innerHTML = `<span class="context-label">售后</span><h3>${escapeHtml(ticketLabels[ticket.ticket_type])}</h3><p>${escapeHtml(ticket.external_id)} · ${escapeHtml(ticket.description || "待补充问题说明")}</p>${statusBadge(ticket.status)}${contextLink("after-sales", ticket.external_id, "查看售后详情")}`;
    createButton.textContent = "查看关联售后";
    createButton.disabled = false;
    createButton.onclick = () => { window.location.href = routeHref("after-sales", { ticket: ticket.external_id, return_conversation: state.conversationId }); };
  } else {
    $("#workOrderContextCard").innerHTML = '<span class="context-label">售后</span><div class="context-empty">暂无关联工单</div>';
    createButton.textContent = "创建售后工单";
    createButton.disabled = false;
    createButton.onclick = openTicketDialog;
  }
  const links = [
    `<span>会话 ${escapeHtml(customer.source_external_id || customer.id)}</span>`,
    context.order ? `<a href="${routeHref("orders", { order: context.order.external_id, return_conversation: state.conversationId })}">订单 ${escapeHtml(context.order.external_id)}</a>` : "",
    context.work_order ? `<a href="${routeHref("after-sales", { ticket: context.work_order.external_id, return_conversation: state.conversationId })}">工单 ${escapeHtml(context.work_order.external_id)}</a>` : "",
  ].filter(Boolean);
  $("#relationBreadcrumb").innerHTML = links.join("<i>›</i>");
  const related = [context.order && "订单", context.product && "商品", context.work_order && "售后"]
    .filter(Boolean);
  $("#contextFactsSummary").textContent = related.length
    ? `已关联 ${related.join("、")}，点开核对`
    : "暂无订单、商品或售后关联";
}

async function sendMessage(event) {
  event.preventDefault();
  if (!state.conversationId) return;
  const fileInput = $("#serviceFile");
  const textInput = $("#serviceMessage");
  const file = fileInput.files[0];
  const content = textInput.value.trim();
  if (!file && !content) return;
  const submit = event.currentTarget.querySelector("button[type='submit']");
  submit.disabled = true;
  try {
    const sent = file
      ? await api.sendMedia(state.conversationId, file, messageTypeForFile(file), content)
      : await api.sendText(state.conversationId, content);
    timeline.add(sent);
    markAssistanceStale();
    textInput.value = "";
    autoGrow(textInput);
    fileInput.value = "";
    $("#serviceAttachment").hidden = true;
    $("#serviceComposerStatus").textContent = "消息已保存并实时同步";
  } catch (error) {
    $("#serviceComposerStatus").textContent = errorMessage(error);
  } finally {
    submit.disabled = false;
  }
}

async function searchMessages(event) {
  event.preventDefault();
  const q = new FormData(event.currentTarget).get("q");
  const target = $("#messageSearchResults");
  target.innerHTML = '<div class="empty-compact">正在搜索…</div>';
  try {
    const result = await api.searchMessages({ q, page_size: 30 });
    target.innerHTML = result.items.map((item) => `<button type="button" data-search-conversation="${escapeHtml(item.conversation_id)}" data-message-id="${item.id}"><strong>${escapeHtml(item.buyer_nickname || item.conversation_source_external_id)}</strong><span>${escapeHtml(item.content)}</span><small>${formatDate(item.created_at)}</small></button>`).join("") || '<div class="empty-compact">没有找到相关消息</div>';
    $$('[data-search-conversation]', target).forEach((button) => button.addEventListener("click", async () => {
      const conversation = state.conversations.find((item) => item.id === button.dataset.searchConversation);
      if (conversation) await selectConversation(conversation);
    }));
  } catch (error) {
    target.innerHTML = `<div class="empty-compact">${escapeHtml(errorMessage(error))}</div>`;
  }
}

function paginationText(result) {
  const start = result.total ? (result.page - 1) * result.page_size + 1 : 0;
  const end = Math.min(result.page * result.page_size, result.total);
  return `<span>显示 ${start}–${end}，共 ${result.total} 条</span>`;
}

async function loadOrders() {
  const params = Object.fromEntries(new FormData($("#orderFilters")));
  $("#ordersTableBody").innerHTML = '<tr><td colspan="7"><div class="empty-compact">正在读取订单…</div></td></tr>';
  try {
    const result = await api.managementOrders(params);
    $("#ordersTableBody").innerHTML = result.items.map((order) => `<tr data-order-id="${escapeHtml(order.external_id)}"><td><strong>${escapeHtml(order.external_id)}</strong><small>${formatDate(order.ordered_at)}</small></td><td>${escapeHtml(order.buyer_nickname || order.customer_id)}</td><td>${escapeHtml(order.product_name || order.product_external_id || "—")}<small>× ${order.quantity}</small></td><td>${badge(orderStatusLabel(order.status), "active")}</td><td>${formatMoney(order.total_amount)}</td><td>${escapeHtml(order.logistics_company || "—")}<small>${escapeHtml(order.logistics_no || "暂无单号")}</small></td><td>${order.work_order_external_id ? badge("已有售后", "warning") : badge("无售后")}</td></tr>`).join("") || '<tr><td colspan="7"><div class="empty-compact">没有符合条件的订单</div></td></tr>';
    $("#ordersPagination").innerHTML = paginationText(result);
    $$('[data-order-id]').forEach((row) => makeRowInteractive(row, `查看订单 ${row.dataset.orderId}`, () => openOrder(row.dataset.orderId)));
  } catch (error) {
    renderTableError($("#ordersTableBody"), 7, error, loadOrders);
    showToast(elements.toasts, errorMessage(error), "error");
  }
}

function makeRowInteractive(row, label, action) {
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.setAttribute("aria-label", label);
  row.addEventListener("click", action);
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  });
}

function renderTableError(target, columns, error, retry) {
  target.innerHTML = `<tr><td colspan="${columns}"><button class="empty-compact retry-action" type="button">${escapeHtml(errorMessage(error))}<span>重新加载</span></button></td></tr>`;
  $(".retry-action", target).addEventListener("click", retry);
}

function openDrawer(html, queryKey, id) {
  state.drawerTrigger = document.activeElement;
  elements.drawerContent.innerHTML = html;
  elements.drawer.classList.add("is-open");
  elements.drawer.setAttribute("aria-hidden", "false");
  elements.drawerScrim.hidden = false;
  document.body.classList.add("drawer-open");
  setUrlParam(queryKey, id);
  requestAnimationFrame(() => $("#drawerClose").focus());
}

function closeDrawer() {
  elements.drawer.classList.remove("is-open");
  elements.drawer.setAttribute("aria-hidden", "true");
  elements.drawerScrim.hidden = true;
  document.body.classList.remove("drawer-open");
  ["order", "ticket", "product", "assistant"].forEach((key) => setUrlParam(key, null));
  state.drawerTrigger?.focus?.();
  state.drawerTrigger = null;
}

function returnToConversationLink() {
  const id = new URLSearchParams(window.location.search).get("return_conversation");
  return id ? `<a class="button button-secondary button-full" href="${routeHref("chat", { conversation: id })}">← 返回原会话</a>` : "";
}

async function openOrder(id) {
  try {
    const order = await api.managementOrder(id);
    openDrawer(`<span class="eyebrow">订单详情</span><h2>${escapeHtml(order.external_id)}</h2><div class="drawer-badges">${badge(orderStatusLabel(order.status), "active")}${order.work_order_external_id ? badge("已关联售后", "warning") : ""}</div><dl class="detail-list"><dt>买家</dt><dd>${escapeHtml(order.buyer_nickname || order.customer_id)}</dd><dt>商品</dt><dd>${escapeHtml(order.product_name || order.product_external_id || "—")} × ${order.quantity}</dd><dt>实付金额</dt><dd>${formatMoney(order.total_amount)}</dd><dt>下单时间</dt><dd>${formatDate(order.ordered_at)}</dd><dt>物流</dt><dd>${escapeHtml(order.logistics_company || "—")} · ${escapeHtml(order.logistics_no || "暂无单号")}</dd></dl><div class="drawer-actions">${order.conversation_id ? `<a class="button button-primary button-full" href="${routeHref("chat", { conversation: order.conversation_id })}">查看原会话</a>` : ""}${order.work_order_external_id ? `<a class="button button-secondary button-full" href="${routeHref("after-sales", { ticket: order.work_order_external_id })}">查看关联售后</a>` : ""}${returnToConversationLink()}</div>`, "order", id);
  } catch (error) { showToast(elements.toasts, errorMessage(error), "error"); }
}

async function loadTickets() {
  const params = Object.fromEntries(new FormData($("#ticketFilters")));
  params.ticket_type = state.ticketType;
  $("#ticketsTableBody").innerHTML = '<tr><td colspan="8"><div class="empty-compact">正在读取工单…</div></td></tr>';
  try {
    const result = await api.workOrders(params);
    $("#ticketsTableBody").innerHTML = result.items.map((ticket) => `<tr data-ticket-id="${escapeHtml(ticket.external_id)}"><td><strong>${escapeHtml(ticket.external_id)}</strong></td><td>${badge(ticketLabels[ticket.ticket_type], "neutral")}</td><td>${escapeHtml(ticket.buyer_nickname || "—")}</td><td>${escapeHtml(ticket.order_external_id || "—")}</td><td>${escapeHtml(ticket.description || "—")}</td><td>${statusBadge(ticket.status)}</td><td>${escapeHtml(ticket.assignee || "待分配")}</td><td>${formatDate(ticket.updated_at)}</td></tr>`).join("") || '<tr><td colspan="8"><div class="empty-compact">没有符合条件的工单</div></td></tr>';
    $("#ticketsPagination").innerHTML = paginationText(result);
    $$('[data-ticket-id]').forEach((row) => makeRowInteractive(row, `查看工单 ${row.dataset.ticketId}`, () => openTicket(row.dataset.ticketId)));
  } catch (error) {
    renderTableError($("#ticketsTableBody"), 8, error, loadTickets);
    showToast(elements.toasts, errorMessage(error), "error");
  }
}

function detailRows(detail) {
  return Object.entries(detail || {}).filter(([, value]) => value !== null && value !== "").map(([key, value]) => `<dt>${escapeHtml(detailFieldLabels[key] || "其他信息")}</dt><dd>${escapeHtml(typeof value === "boolean" ? (value ? "是" : "否") : value)}</dd>`).join("");
}

async function openTicket(id) {
  try {
    const ticket = await api.workOrder(id);
    const nextOptions = ticket.status === "completed"
      ? '<option value="processing">重新处理</option>'
      : ticket.status === "processing"
        ? '<option value="pending">退回待处理</option><option value="completed">已完成</option>'
        : '<option value="processing">处理中</option><option value="completed">已完成</option>';
    openDrawer(`<span class="eyebrow">售后详情</span><h2>${escapeHtml(ticket.external_id)}</h2><div class="drawer-badges">${badge(ticketLabels[ticket.ticket_type])}${statusBadge(ticket.status)}</div><p class="drawer-lead">${escapeHtml(ticket.description || "暂无问题说明")}</p><dl class="detail-list"><dt>买家</dt><dd>${escapeHtml(ticket.buyer_nickname || "—")}</dd><dt>关联订单</dt><dd>${escapeHtml(ticket.order_external_id || "—")}</dd><dt>处理人</dt><dd>${escapeHtml(ticket.assignee || "待分配")}</dd>${detailRows(ticket.detail)}</dl><form class="status-update-form" id="ticketStatusForm"><label>更新状态<select name="status" required><option value="">选择下一状态</option>${nextOptions}</select></label><label>处理备注<textarea name="note" required rows="3"></textarea></label><button class="button button-primary button-full">保存状态</button></form><div class="timeline-list">${ticket.status_logs.map((log) => `<article><strong>${escapeHtml(statusLabels[log.to_status] || log.to_status)}</strong><span>${escapeHtml(log.note || "")}</span><small>${formatDate(log.created_at)}</small></article>`).join("")}</div><div class="drawer-actions">${ticket.conversation_id ? `<a class="button button-secondary button-full" href="${routeHref("chat", { conversation: ticket.conversation_id })}">查看原会话</a>` : ""}${returnToConversationLink()}</div>`, "ticket", id);
    $("#ticketStatusForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(event.currentTarget));
      try { await api.updateWorkOrderStatus(id, payload); showToast(elements.toasts, "工单状态已更新"); await loadTickets(); await loadSummary(); await openTicket(id); } catch (error) { showToast(elements.toasts, errorMessage(error), "error"); }
    });
  } catch (error) { showToast(elements.toasts, errorMessage(error), "error"); }
}

async function loadProducts() {
  const params = Object.fromEntries(new FormData($("#productFilters")));
  $("#productsGrid").innerHTML = '<div class="empty-compact">正在读取商品…</div>';
  try {
    const result = await api.managementProducts(params);
    $("#productsGrid").innerHTML = result.items.map((product) => `<button class="product-management-card" type="button" data-product-id="${escapeHtml(product.external_id)}"><span class="product-swatch" aria-hidden="true"></span><span class="eyebrow">${escapeHtml(product.sku || product.external_id)}</span><h3>${escapeHtml(product.name)}</h3><p>${escapeHtml(product.description || "来自业务订单的商品档案")}</p><strong>${formatMoney(product.price)}</strong><small>查看档案 →</small></button>`).join("") || '<div class="empty-compact">没有符合条件的商品</div>';
    $("#productsPagination").innerHTML = paginationText(result);
    $$('[data-product-id]').forEach((card) => card.addEventListener("click", () => openProduct(card.dataset.productId)));
  } catch (error) {
    $("#productsGrid").innerHTML = `<button class="empty-compact retry-action" type="button">${escapeHtml(errorMessage(error))}<span>重新加载</span></button>`;
    $(".retry-action", $("#productsGrid")).addEventListener("click", loadProducts);
    showToast(elements.toasts, errorMessage(error), "error");
  }
}

async function openProduct(id) {
  try {
    const product = await api.managementProduct(id);
    openDrawer(`<span class="eyebrow">商品详情</span><h2>${escapeHtml(product.name)}</h2><div class="drawer-badges">${badge(product.external_id)}${product.brand ? badge(product.brand, "active") : ""}</div><p class="drawer-lead">${escapeHtml(product.description || "暂无商品描述")}</p><dl class="detail-list"><dt>SKU</dt><dd>${escapeHtml(product.sku || "—")}</dd><dt>当前价格</dt><dd>${formatMoney(product.price)}</dd><dt>更新时间</dt><dd>${formatDate(product.updated_at)}</dd></dl><a class="button button-secondary button-full" href="${routeHref("orders", { q: product.external_id })}">查看相关订单</a>${returnToConversationLink()}`, "product", id);
  } catch (error) { showToast(elements.toasts, errorMessage(error), "error"); }
}

function renderRiskOverview(overview) {
  $("#riskWarningCount").textContent = overview.warning_count;
  $("#riskHighCount").textContent = overview.high_risk_count;
  $("#riskAnalyzedCount").textContent = overview.analyzed_count;
  $("#riskFailureCount").textContent = `失败 ${overview.failure_count}`;
  $("#riskClosureRate").textContent = `${Math.round(overview.closure_rate * 100)}%`;
  $("#navRiskCount").textContent = overview.warning_count;
  const max = Math.max(1, ...overview.trend.map((point) => point.warning_count));
  $("#riskTrendChart").innerHTML = overview.trend.map((point) => `
    <div class="risk-bar"><strong>${point.warning_count}</strong><i style="height:${Math.max(7, (point.warning_count / max) * 100)}%"></i><small>${escapeHtml(point.date.slice(5))}</small></div>`).join("");
}

function riskTypeLabel(value) {
  return {
    none: "无预警", emotion_escalation: "情绪升级", repeat_contact: "重复进线",
    repeat_refund: "重复退款", complaint: "舆情投诉",
  }[value] || value;
}

function renderRiskList(result) {
  $("#riskListCount").textContent = `共 ${result.total} 条`;
  $("#riskList").innerHTML = result.items.map((item) => `
    <button class="risk-row${state.selectedRiskConversation === item.conversation_id ? " is-selected" : ""}" type="button" data-risk-conversation="${escapeHtml(item.conversation_id)}">
      <time>${escapeHtml(formatDate(item.updated_at))}</time>
      <span><strong>${escapeHtml(item.buyer_nickname || item.conversation_id)}</strong><small>${escapeHtml(item.summary)}</small></span>
      <b data-severity="${escapeHtml(item.severity)}">${escapeHtml(riskTypeLabel(item.risk_type))}</b>
      <em>${escapeHtml(item.severity === "high" ? "高" : item.severity === "medium" ? "中" : "低")}</em>
      <mark data-status="${escapeHtml(item.status)}">${escapeHtml(item.status === "succeeded" ? "已分析" : item.status === "failed" ? "失败" : "待更新")}</mark>
      <i>${escapeHtml(item.assignee || "未分配")}</i><u>详情</u>
    </button>`).join("") || '<p class="compact-placeholder">当前筛选下没有预警</p>';
  $$('[data-risk-conversation]').forEach((row) => row.addEventListener("click", () => {
    state.selectedRiskConversation = row.dataset.riskConversation;
    $$(".risk-row", $("#riskList")).forEach((candidate) => candidate.classList.toggle("is-selected", candidate === row));
    openRiskDetail(row.dataset.riskConversation);
  }));
}

async function loadRiskData() {
  const generation = ++state.riskGeneration;
  try {
    const [overview, list] = await Promise.all([
      api.emotionOverview(),
      api.emotionAnalyses({ risk_type: state.riskType, page_size: 200 }),
    ]);
    if (generation !== state.riskGeneration || state.view !== "risk") return;
    renderRiskOverview(overview);
    renderRiskList(list);
  } catch (error) {
    if (generation !== state.riskGeneration) return;
    $("#riskList").innerHTML = `<p class="compact-placeholder">${escapeHtml(errorMessage(error))}</p>`;
  }
}

async function openRiskDetail(conversationId) {
  const generation = ++state.riskDetailGeneration;
  try {
    const item = await api.emotionAnalysis(conversationId);
    if (generation !== state.riskDetailGeneration) return;
    openDrawer(`<span class="eyebrow">情绪风险详情</span><h2>${escapeHtml(item.buyer_nickname || item.conversation_id)}</h2><div class="drawer-badges">${badge(riskTypeLabel(item.risk_type), "warning")}${badge(item.severity === "high" ? "高风险" : "需关注", "active")}</div><p class="drawer-lead">${escapeHtml(item.summary)}</p><dl class="detail-list"><dt>情绪判断</dt><dd>${escapeHtml(emotionLabels[item.emotion] || item.emotion)} · ${Math.round(item.confidence * 100)}%</dd><dt>处理人</dt><dd>${escapeHtml(item.assignee || "未分配")}</dd><dt>分析时间</dt><dd>${escapeHtml(formatDate(item.analyzed_at))}</dd></dl><a class="button button-primary button-full" href="${routeHref("chat", { conversation: item.conversation_id })}">查看原会话</a>`, "risk", conversationId);
  } catch (error) { showToast(elements.toasts, errorMessage(error), "error"); }
}

function renderRiskRun(run) {
  const active = ["queued", "running"].includes(run.status);
  const ratio = run.total_count ? Math.round((run.processed_count / run.total_count) * 100) : 0;
  $("#riskProgress").hidden = !active;
  $("#riskProgressText").textContent = active
    ? `正在分析 ${run.processed_count}/${run.total_count}`
    : run.status === "completed" ? "增量分析已完成" : `已完成，失败 ${run.failed_count}`;
  $("#riskProgressBar").style.width = `${ratio}%`;
  $("#riskRunStatus").textContent = active
    ? `后台低思考分析中：${run.processed_count}/${run.total_count}`
    : "已展示最新持久化分析结果。";
  return active;
}

async function pollRiskRun() {
  window.clearTimeout(state.riskPollTimer);
  try {
    const run = await api.currentEmotionRun();
    const active = renderRiskRun(run);
    await loadRiskData();
    if (active && state.view === "risk") {
      state.riskPollTimer = window.setTimeout(pollRiskRun, 1500);
    }
  } catch (error) {
    $("#riskRunStatus").textContent = errorMessage(error);
  }
}

async function startRiskAnalysis() {
  try {
    const run = await api.startEmotionRun();
    renderRiskRun(run);
    void pollRiskRun();
  } catch (error) { showToast(elements.toasts, errorMessage(error), "error"); }
}

function initializeRisk() {
  $("#refreshRiskAnalysis").addEventListener("click", startRiskAnalysis);
  $$('[data-risk-type]').forEach((button) => button.addEventListener("click", () => {
    state.riskType = button.dataset.riskType;
    $$('[data-risk-type]').forEach((item) => item.classList.toggle("is-active", item === button));
    void loadRiskData();
  }));
  void loadRiskData().then(startRiskAnalysis);
}

function openTicketDialog() {
  if (!state.context) return;
  const form = $("#createTicketForm");
  form.elements.conversation_id.value = state.context.conversation.id;
  form.elements.order_external_id.value = state.context.order?.external_id || "";
  form.elements.buyer_nickname.value = state.context.conversation.buyer_nickname || "";
  elements.ticketDialog.showModal();
}

async function createTicket(event) {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  const payload = { ...values, customer_id: values.buyer_nickname || null, status: "pending", detail: {} };
  try {
    const ticket = await api.createWorkOrder(payload);
    elements.ticketDialog.close();
    showToast(elements.toasts, "售后工单已创建并关联当前会话");
    state.context = await api.conversationContext(state.conversationId);
    renderContext(state.context);
    await loadSummary();
    window.location.href = routeHref("after-sales", { ticket: ticket.external_id, return_conversation: state.conversationId });
  } catch (error) { showToast(elements.toasts, errorMessage(error), "error"); }
}

function initializeImport() {
  $$('[data-open-import]').forEach((button) => button.addEventListener("click", () => elements.importDialog.showModal()));
  $("#workbookImportForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = event.currentTarget.elements.file.files[0];
    elements.importPreview.innerHTML = '<div class="empty-compact">正在检查七张业务表与关联关系…</div>';
    try {
      const preview = await api.previewWorkbook(file);
      const workOrders = Object.values(preview.work_order_types).reduce((sum, value) => sum + value, 0);
      elements.importPreview.innerHTML = `<div class="import-result ${preview.can_commit ? "is-ready" : "is-invalid"}"><h3>${preview.can_commit ? "校验通过，可以导入" : "发现错误，暂不能导入"}</h3><div class="import-counts"><span><strong>${preview.sheets["聊天记录"] || 0}</strong>聊天</span><span><strong>${preview.sheets["订单"] || 0}</strong>订单</span><span><strong>${workOrders}</strong>工单</span></div>${preview.errors.slice(0, 8).map((error) => `<p>${escapeHtml(error.sheet_name)} 第 ${error.row_number} 行：${escapeHtml(error.message)}</p>`).join("")}${preview.can_commit ? `<button class="button button-primary button-full" id="commitWorkbook" type="button">确认写入数据库</button>` : ""}</div>`;
      $("#commitWorkbook")?.addEventListener("click", async () => {
        try {
          const result = await api.commitWorkbook(preview.batch_id);
          const total = Object.values(result.created).reduce((sum, value) => sum + value, 0);
          elements.importPreview.innerHTML = `<div class="import-result is-ready"><h3>导入完成</h3><p>本次新增 ${total} 条业务记录；重复文件会安全更新，不会重复累加。</p></div>`;
          showToast(elements.toasts, "业务工作簿已导入");
          await loadSummary();
          if (state.view === "orders") await loadOrders();
          if (state.view === "after-sales") await loadTickets();
          if (state.view === "products") await loadProducts();
        } catch (error) { showToast(elements.toasts, errorMessage(error), "error"); }
      });
    } catch (error) { elements.importPreview.innerHTML = `<div class="empty-compact">${escapeHtml(errorMessage(error))}</div>`; }
  });
}

function initializeChat() {
  $("#conversationFilter").addEventListener("submit", (event) => { event.preventDefault(); loadConversations(); });
  $("#messageSearchForm").addEventListener("submit", searchMessages);
  $("#serviceComposer").addEventListener("submit", sendMessage);
  $("#serviceMessage").addEventListener("input", (event) => autoGrow(event.currentTarget));
  $("#serviceMessage").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("#serviceComposer").requestSubmit();
    }
  });
  $("#serviceFile").addEventListener("change", (event) => {
    const file = event.currentTarget.files[0];
    $("#serviceAttachment").hidden = !file;
    $("#serviceAttachmentName").textContent = file ? `${file.name} · ${messageTypeLabel(messageTypeForFile(file))}` : "";
  });
  $("#serviceAttachmentClear").addEventListener("click", () => {
    $("#serviceFile").value = "";
    $("#serviceAttachment").hidden = true;
  });
  $("#createTicketFromChat").addEventListener("click", openTicketDialog);
  $("#runAssistance").addEventListener("click", runAssistance);
  $("#openAssistance").addEventListener("click", showAssistanceDetails);
  $("#useAssistanceReplyInline").addEventListener("click", () => {
    if (state.assistance) useAssistanceReply(state.assistance);
  });
  $("#createTicketForm").addEventListener("submit", createTicket);
  loadConversations();
}

function initializeView() {
  if (state.view === "chat") initializeChat();
  if (state.view === "orders") {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) $("#orderFilters").elements.q.value = q;
    $("#orderFilters").addEventListener("submit", (event) => { event.preventDefault(); loadOrders(); });
    loadOrders();
  }
  if (state.view === "after-sales") {
    $("#ticketFilters").addEventListener("submit", (event) => { event.preventDefault(); loadTickets(); });
    $$('[data-ticket-type]').forEach((button) => button.addEventListener("click", () => {
      state.ticketType = button.dataset.ticketType;
      $$('[data-ticket-type]').forEach((item) => item.classList.toggle("is-active", item === button));
      loadTickets();
    }));
    loadTickets();
  }
  if (state.view === "products") {
    $("#productFilters").addEventListener("submit", (event) => { event.preventDefault(); loadProducts(); });
    loadProducts();
  }
  if (state.view === "risk") initializeRisk();
  const params = new URLSearchParams(window.location.search);
  if (state.view === "orders" && params.get("order")) openOrder(params.get("order"));
  if (state.view === "after-sales" && params.get("ticket")) openTicket(params.get("ticket"));
  if (state.view === "products" && params.get("product")) openProduct(params.get("product"));
}

elements.drawerScrim.addEventListener("click", closeDrawer);
$("#drawerClose").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (elements.drawer.classList.contains("is-open")) closeDrawer();
  else if (document.body.classList.contains("nav-open")) setMobileNavigation(false);
});
window.addEventListener("beforeunload", () => {
  socket.close();
  window.clearTimeout(state.riskPollTimer);
});
initializeShell();
initializeImport();
initializeView();
loadSummary();
