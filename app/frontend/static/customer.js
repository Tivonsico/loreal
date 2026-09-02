import { api, ConversationSocket } from "./api.js?v=20260810-2";
import {
  MessageTimeline,
  autoGrow,
  conversationButton,
  messageTypeLabel,
  messageTypeForFile,
  orderCard,
  productCard,
  renderCollection,
  setConnectionState,
  showToast,
} from "./chat.js?v=20260810-1";

const $ = (selector) => document.querySelector(selector);
const state = {
  customerId: localStorage.getItem("beauty.customer_id") || "",
  conversationId: localStorage.getItem("beauty.customer_conversation") || null,
  conversations: [],
};

const elements = {
  customerIdForm: $("#customerIdForm"),
  customerId: $("#customerId"),
  conversationList: $("#customerConversationList"),
  refreshConversations: $("#refreshCustomerConversations"),
  newConversationForm: $("#newConversationForm"),
  conversationTitle: $("#conversationTitle"),
  chatEmpty: $("#customerChatEmpty"),
  chatView: $("#customerChatView"),
  chatMeta: $("#customerChatMeta"),
  chatTitle: $("#customerChatTitle"),
  chatId: $("#customerChatId"),
  messages: $("#customerMessages"),
  composer: $("#customerComposer"),
  message: $("#customerMessage"),
  file: $("#customerFile"),
  attachment: $("#customerAttachment"),
  attachmentName: $("#customerAttachmentName"),
  attachmentClear: $("#customerAttachmentClear"),
  composerStatus: $("#customerComposerStatus"),
  connection: $("#connectionStatus"),
  connectionText: $("#connectionText"),
  businessToggle: $("#businessToggle"),
  businessClose: $("#businessClose"),
  productSearch: $("#customerProductSearch"),
  productList: $("#customerProductList"),
  productListToggle: $("#customerProductListToggle"),
  orderContext: $("#customerOrderContext"),
  orderFilter: $("#customerOrderFilter"),
  orderList: $("#customerOrderList"),
  afterSalesList: $("#customerAfterSalesList"),
  toasts: $("#customerToasts"),
};

const timeline = new MessageTimeline(elements.messages, "customer");
const socket = new ConversationSocket({
  onState: (value) => setConnectionState(elements.connection, elements.connectionText, value),
  onMessage: (message) => {
    if (message.conversation_id === state.conversationId) timeline.add(message);
  },
});

function errorMessage(error) {
  return error?.message || "请求没有完成，请稍后重试";
}

function setBusy(form, busy) {
  form.querySelectorAll("button, input, textarea").forEach((control) => {
    control.disabled = busy;
  });
}

function renderConversations() {
  elements.conversationList.replaceChildren();
  if (!state.conversations.length) {
    const empty = document.createElement("div");
    empty.className = "empty-compact";
    empty.textContent = "该客户编号下暂无会话，可以创建第一段咨询。";
    elements.conversationList.append(empty);
    return;
  }
  state.conversations.forEach((conversation) => {
    const button = conversationButton(conversation, state.conversationId);
    button.addEventListener("click", () => selectConversation(conversation));
    elements.conversationList.append(button);
  });
}

async function loadConversations({ silent = false } = {}) {
  if (!state.customerId) return;
  try {
    state.conversations = await api.listConversations({ customer_id: state.customerId });
    renderConversations();
    const current = state.conversations.find((item) => item.id === state.conversationId);
    if (current && elements.chatView.hidden) await selectConversation(current);
    if (!current && state.conversationId) {
      state.conversationId = null;
      localStorage.removeItem("beauty.customer_conversation");
      showChatEmpty();
    }
  } catch (error) {
    if (!silent) showToast(elements.toasts, errorMessage(error), "error");
  }
}

async function selectConversation(conversation) {
  state.conversationId = conversation.id;
  localStorage.setItem("beauty.customer_conversation", conversation.id);
  elements.chatEmpty.hidden = true;
  elements.chatView.hidden = false;
  elements.chatMeta.textContent = `客户 · ${conversation.customer_id}`;
  elements.chatTitle.textContent = conversation.title || "未命名咨询";
  elements.chatId.textContent = conversation.id;
  renderConversations();
  elements.messages.replaceChildren();
  const loading = document.createElement("div");
  loading.className = "empty-compact";
  loading.textContent = "正在读取消息…";
  elements.messages.append(loading);
  try {
    const page = await api.listMessages(conversation.id, { limit: 200 });
    if (state.conversationId !== conversation.id) return;
    timeline.reset(page.items);
    socket.connect(conversation.id);
  } catch (error) {
    timeline.reset([]);
    showToast(elements.toasts, errorMessage(error), "error");
  }
}

function showChatEmpty() {
  socket.close();
  elements.chatEmpty.hidden = false;
  elements.chatView.hidden = true;
}

async function applyCustomerId(value) {
  const customerId = value.trim();
  if (!customerId) {
    showToast(elements.toasts, "请输入业务客户编号", "error");
    return;
  }
  if (state.customerId !== customerId) {
    state.conversationId = null;
    localStorage.removeItem("beauty.customer_conversation");
    showChatEmpty();
  }
  state.customerId = customerId;
  localStorage.setItem("beauty.customer_id", customerId);
  elements.customerId.value = customerId;
  elements.newConversationForm.hidden = false;
  elements.orderContext.textContent = `当前按业务客户编号 ${customerId} 查询；这不是身份验证。`;
  await Promise.all([loadConversations(), loadOrders(), loadAfterSales()]);
}

async function createConversation(event) {
  event.preventDefault();
  if (!state.customerId) {
    showToast(elements.toasts, "请先输入业务客户编号", "error");
    return;
  }
  setBusy(elements.newConversationForm, true);
  try {
    const conversation = await api.createConversation({
      customer_id: state.customerId,
      title: elements.conversationTitle.value.trim() || null,
    });
    elements.conversationTitle.value = "";
    await loadConversations();
    await selectConversation(conversation);
    showToast(elements.toasts, "新咨询已创建");
  } catch (error) {
    showToast(elements.toasts, errorMessage(error), "error");
  } finally {
    setBusy(elements.newConversationForm, false);
  }
}

function clearAttachment() {
  elements.file.value = "";
  elements.attachment.hidden = true;
  elements.attachmentName.textContent = "";
}

async function sendMessage(event) {
  event.preventDefault();
  if (!state.conversationId) {
    showToast(elements.toasts, "请先选择一段会话", "error");
    return;
  }
  const file = elements.file.files[0];
  const content = elements.message.value.trim();
  if (!file && !content) return;
  const submit = elements.composer.querySelector("button[type='submit']");
  submit.disabled = true;
  elements.composerStatus.classList.remove("is-error");
  elements.composerStatus.textContent = file ? "正在上传并发送附件…" : "正在发送…";
  try {
    const sent = file
      ? await api.sendMedia(state.conversationId, file, messageTypeForFile(file), content)
      : await api.sendText(state.conversationId, content);
    timeline.add(sent);
    elements.message.value = "";
    autoGrow(elements.message);
    clearAttachment();
    elements.composerStatus.textContent = "消息已保存；实时连接负责通知另一端";
    await loadConversations({ silent: true });
  } catch (error) {
    elements.composerStatus.classList.add("is-error");
    elements.composerStatus.textContent = errorMessage(error);
  } finally {
    submit.disabled = false;
  }
}

async function loadProducts(query = "") {
  try {
    const products = await api.listProducts({ q: query, limit: 100 });
    renderCollection(elements.productList, products, productCard, "暂无商品数据");
  } catch (error) {
    renderCollection(elements.productList, [], productCard, errorMessage(error));
  }
}

function setProductListExpanded(expanded) {
  elements.productList.hidden = !expanded;
  elements.productListToggle.setAttribute("aria-expanded", String(expanded));
  elements.productListToggle.textContent = expanded ? "收起商品列表" : "展开商品列表";
}

async function loadOrders(status = "") {
  if (!state.customerId) {
    renderCollection(elements.orderList, [], orderCard, "输入业务客户编号后查询订单");
    return;
  }
  try {
    const orders = await api.listOrders({
      customer_id: state.customerId,
      status,
      limit: 100,
    });
    renderCollection(elements.orderList, orders, orderCard, "该客户编号下暂无订单");
  } catch (error) {
    renderCollection(elements.orderList, [], orderCard, errorMessage(error));
  }
}

async function loadAfterSales() {
  if (!state.customerId) {
    elements.afterSalesList.innerHTML = '<div class="empty-compact">输入客户编号后查看售后进度</div>';
    return;
  }
  const typeLabels = {
    replacement_exchange: "补发换货",
    offline_payment: "退款/补差",
    logistics: "物流处理",
    adverse_reaction: "使用不适登记",
    after_sale_return: "退货退款",
  };
  const statusLabels = { pending: "待处理", processing: "处理中", completed: "已完成" };
  try {
    const records = await api.publicAfterSales(state.customerId);
    elements.afterSalesList.replaceChildren();
    records.forEach((record) => {
      const card = document.createElement("article");
      card.className = "data-card public-after-sales-card";
      const title = document.createElement("h3");
      title.textContent = typeLabels[record.ticket_type] || record.ticket_type;
      const summary = document.createElement("p");
      if (record.replacement_tracking_no) {
        summary.textContent = `补发物流：${record.replacement_tracking_no}`;
      } else if (record.confirmed_payment_status) {
        const amount = record.confirmed_payment_amount ? ` · ¥${record.confirmed_payment_amount}` : "";
        summary.textContent = `退款进度：${record.confirmed_payment_status}${amount}`;
      } else {
        summary.textContent = "客服团队正在按流程跟进";
      }
      const meta = document.createElement("div");
      meta.className = "data-card-meta";
      const id = document.createElement("span");
      id.textContent = record.external_id;
      const status = document.createElement("strong");
      status.textContent = statusLabels[record.status] || record.status;
      meta.append(id, status);
      card.append(title, summary, meta);
      elements.afterSalesList.append(card);
    });
    if (!records.length) {
      elements.afterSalesList.innerHTML = '<div class="empty-compact">当前没有售后处理记录</div>';
    }
  } catch (error) {
    elements.afterSalesList.innerHTML = `<div class="empty-compact">${errorMessage(error)}</div>`;
  }
}

function switchBusinessTab(name) {
  document.querySelectorAll("[data-customer-tab]").forEach((button) => {
    const active = button.dataset.customerTab === name;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
    const active = panel.dataset.tabPanel === name;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  if (name === "orders") loadOrders();
  if (name === "after-sales") loadAfterSales();
}

function bindEvents() {
  elements.customerIdForm.addEventListener("submit", (event) => {
    event.preventDefault();
    applyCustomerId(elements.customerId.value);
  });
  elements.newConversationForm.addEventListener("submit", createConversation);
  elements.refreshConversations.addEventListener("click", () => loadConversations());
  elements.composer.addEventListener("submit", sendMessage);
  elements.message.addEventListener("input", () => autoGrow(elements.message));
  elements.message.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      elements.composer.requestSubmit();
    }
  });
  elements.file.addEventListener("change", () => {
    const file = elements.file.files[0];
    elements.attachment.hidden = !file;
    elements.attachmentName.textContent = file ? `${file.name} · ${messageTypeLabel(messageTypeForFile(file))}` : "";
  });
  elements.attachmentClear.addEventListener("click", clearAttachment);
  elements.businessToggle.addEventListener("click", () => {
    document.body.classList.add("business-open");
    elements.businessToggle.setAttribute("aria-expanded", "true");
  });
  elements.businessClose.addEventListener("click", () => {
    document.body.classList.remove("business-open");
    elements.businessToggle.setAttribute("aria-expanded", "false");
  });
  document.querySelectorAll("[data-customer-tab]").forEach((button) => {
    button.addEventListener("click", () => switchBusinessTab(button.dataset.customerTab));
  });
  elements.productListToggle.addEventListener("click", () => {
    setProductListExpanded(elements.productList.hidden);
  });
  elements.productSearch.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = new FormData(elements.productSearch).get("q") || "";
    setProductListExpanded(true);
    await loadProducts(query);
  });
  elements.orderFilter.addEventListener("submit", (event) => {
    event.preventDefault();
    loadOrders(new FormData(elements.orderFilter).get("status") || "");
  });
}

async function init() {
  bindEvents();
  try {
    const health = await api.health();
    if (health.role !== "customer") throw new Error("当前端口不是客户入口");
  } catch (error) {
    showToast(elements.toasts, errorMessage(error), "error");
  }
  await loadProducts();
  if (state.customerId) await applyCustomerId(state.customerId);
  window.setInterval(() => loadConversations({ silent: true }), 3000);
}

init();
