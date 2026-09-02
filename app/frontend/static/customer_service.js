import { api, ConversationSocket } from "./api.js?v=20260810-2";
import {
  MessageTimeline,
  autoGrow,
  conversationButton,
  messageTypeLabel,
  messageTypeForFile,
  normalizedItemsPayload,
  orderCard,
  parseJsonInput,
  productCard,
  renderCollection,
  setConnectionState,
  showToast,
} from "./chat.js?v=20260810-1";

const $ = (selector) => document.querySelector(selector);
const state = {
  conversations: [],
  conversationId: localStorage.getItem("beauty.service_conversation") || null,
  currentConversation: null,
};

const elements = {
  conversationFilter: $("#serviceConversationFilter"),
  customerFilter: $("#serviceCustomerFilter"),
  statusFilter: $("#serviceStatusFilter"),
  clearFilters: $("#clearServiceFilters"),
  conversationList: $("#serviceConversationList"),
  conversationCount: $("#conversationCount"),
  chatEmpty: $("#serviceChatEmpty"),
  chatView: $("#serviceChatView"),
  chatMeta: $("#serviceChatMeta"),
  chatTitle: $("#serviceChatTitle"),
  customerId: $("#serviceCustomerId"),
  conversationId: $("#serviceConversationId"),
  messages: $("#serviceMessages"),
  composer: $("#serviceComposer"),
  message: $("#serviceMessage"),
  file: $("#serviceFile"),
  attachment: $("#serviceAttachment"),
  attachmentName: $("#serviceAttachmentName"),
  attachmentClear: $("#serviceAttachmentClear"),
  composerStatus: $("#serviceComposerStatus"),
  connection: $("#serviceConnectionStatus"),
  connectionText: $("#serviceConnectionText"),
  productSearch: $("#serviceProductSearch"),
  productList: $("#serviceProductList"),
  createProduct: $("#createProductForm"),
  importProducts: $("#importProductsForm"),
  orderFilter: $("#serviceOrderFilter"),
  orderList: $("#serviceOrderList"),
  createOrder: $("#createOrderForm"),
  importOrders: $("#importOrdersForm"),
  toasts: $("#serviceToasts"),
};

const timeline = new MessageTimeline(elements.messages, "customer_service");
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

function currentFilters() {
  const data = new FormData(elements.conversationFilter);
  return {
    customer_id: data.get("customer_id") || "",
    status: data.get("status") || "",
    limit: 500,
  };
}

function renderConversations() {
  elements.conversationCount.textContent = String(state.conversations.length);
  elements.conversationList.replaceChildren();
  if (!state.conversations.length) {
    const empty = document.createElement("div");
    empty.className = "empty-compact";
    empty.textContent = "当前筛选条件下暂无会话";
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
  try {
    state.conversations = await api.listConversations(currentFilters());
    renderConversations();
    if (state.conversationId && !state.currentConversation) {
      const remembered = state.conversations.find((item) => item.id === state.conversationId);
      if (remembered) await selectConversation(remembered);
    }
  } catch (error) {
    if (!silent) showToast(elements.toasts, errorMessage(error), "error");
  }
}

async function selectConversation(conversation) {
  state.currentConversation = conversation;
  state.conversationId = conversation.id;
  localStorage.setItem("beauty.service_conversation", conversation.id);
  elements.chatEmpty.hidden = true;
  elements.chatView.hidden = false;
  elements.chatMeta.textContent = `CUSTOMER · ${conversation.customer_id}`;
  elements.chatTitle.textContent = conversation.title || "未命名咨询";
  elements.customerId.textContent = conversation.customer_id;
  elements.conversationId.textContent = conversation.id;
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
    prefillOrderContext(conversation);
    await loadOrders({ customer_id: conversation.customer_id });
  } catch (error) {
    timeline.reset([]);
    showToast(elements.toasts, errorMessage(error), "error");
  }
}

function prefillOrderContext(conversation) {
  const orderFilterCustomer = elements.orderFilter.elements.customer_id;
  const orderCustomer = elements.createOrder.elements.customer_id;
  const orderConversation = elements.createOrder.elements.conversation_id;
  orderFilterCustomer.value = conversation.customer_id;
  orderCustomer.value = conversation.customer_id;
  orderConversation.value = conversation.id;
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
    elements.composerStatus.textContent = "消息已保存，发送者角色为 customer_service";
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
    const products = await api.listProducts({ q: query, limit: 1000 });
    renderCollection(elements.productList, products, productCard, "暂无商品，可使用下方表单新增或导入");
  } catch (error) {
    renderCollection(elements.productList, [], productCard, errorMessage(error));
  }
}

async function loadOrders(filters = null) {
  const data = filters || Object.fromEntries(new FormData(elements.orderFilter));
  try {
    const orders = await api.listOrders({ ...data, limit: 1000 });
    renderCollection(elements.orderList, orders, orderCard, "暂无订单，可使用下方表单新增或导入");
  } catch (error) {
    renderCollection(elements.orderList, [], orderCard, errorMessage(error));
  }
}

function optional(value) {
  const text = String(value ?? "").trim();
  return text || null;
}

function optionalNumber(value) {
  const text = String(value ?? "").trim();
  return text === "" ? null : Number(text);
}

function extraJson(value) {
  const text = String(value ?? "").trim();
  if (!text) return {};
  const parsed = parseJsonInput(text, "扩展字段");
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("扩展字段必须是 JSON 对象");
  }
  return parsed;
}

async function createProduct(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(elements.createProduct));
  const payload = {
    external_id: data.external_id.trim(),
    name: data.name.trim(),
    sku: optional(data.sku),
    brand: optional(data.brand),
    description: optional(data.description),
    price: optionalNumber(data.price),
    extra: {},
  };
  try {
    payload.extra = extraJson(data.extra);
    setBusy(elements.createProduct, true);
    await api.createProduct(payload);
    elements.createProduct.reset();
    await loadProducts();
    showToast(elements.toasts, `商品 ${payload.external_id} 已新增`);
  } catch (error) {
    showToast(elements.toasts, errorMessage(error), "error");
  } finally {
    setBusy(elements.createProduct, false);
  }
}

async function importProducts(event) {
  event.preventDefault();
  try {
    const items = normalizedItemsPayload(
      new FormData(elements.importProducts).get("payload"),
      "商品导入内容",
    );
    setBusy(elements.importProducts, true);
    const result = await api.importProducts(items);
    await loadProducts();
    showToast(elements.toasts, `商品导入完成：新增 ${result.created}，更新 ${result.updated}`);
  } catch (error) {
    showToast(elements.toasts, errorMessage(error), "error");
  } finally {
    setBusy(elements.importProducts, false);
  }
}

async function createOrder(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(elements.createOrder));
  const payload = {
    external_id: data.external_id.trim(),
    customer_id: data.customer_id.trim(),
    product_external_id: optional(data.product_external_id),
    conversation_id: optional(data.conversation_id),
    status: data.status.trim(),
    quantity: Number(data.quantity),
    total_amount: optionalNumber(data.total_amount),
    extra: {},
  };
  try {
    payload.extra = extraJson(data.extra);
    setBusy(elements.createOrder, true);
    await api.createOrder(payload);
    const current = state.currentConversation;
    elements.createOrder.reset();
    if (current) prefillOrderContext(current);
    await loadOrders({ customer_id: payload.customer_id });
    showToast(elements.toasts, `订单 ${payload.external_id} 已新增`);
  } catch (error) {
    showToast(elements.toasts, errorMessage(error), "error");
  } finally {
    setBusy(elements.createOrder, false);
  }
}

async function importOrders(event) {
  event.preventDefault();
  try {
    const items = normalizedItemsPayload(
      new FormData(elements.importOrders).get("payload"),
      "订单导入内容",
    );
    setBusy(elements.importOrders, true);
    const result = await api.importOrders(items);
    await loadOrders();
    showToast(elements.toasts, `订单导入完成：新增 ${result.created}，更新 ${result.updated}`);
  } catch (error) {
    showToast(elements.toasts, errorMessage(error), "error");
  } finally {
    setBusy(elements.importOrders, false);
  }
}

function switchDataTab(name) {
  document.querySelectorAll("[data-service-tab]").forEach((button) => {
    const active = button.dataset.serviceTab === name;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-service-panel]").forEach((panel) => {
    const active = panel.dataset.servicePanel === name;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  if (name === "orders") loadOrders();
}

function bindEvents() {
  elements.conversationFilter.addEventListener("submit", (event) => {
    event.preventDefault();
    loadConversations();
  });
  elements.clearFilters.addEventListener("click", () => {
    elements.customerFilter.value = "";
    elements.statusFilter.value = "";
    loadConversations();
  });
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
  document.querySelectorAll("[data-service-tab]").forEach((button) => {
    button.addEventListener("click", () => switchDataTab(button.dataset.serviceTab));
  });
  elements.productSearch.addEventListener("submit", (event) => {
    event.preventDefault();
    loadProducts(new FormData(elements.productSearch).get("q") || "");
  });
  elements.createProduct.addEventListener("submit", createProduct);
  elements.importProducts.addEventListener("submit", importProducts);
  elements.orderFilter.addEventListener("submit", (event) => {
    event.preventDefault();
    loadOrders();
  });
  elements.createOrder.addEventListener("submit", createOrder);
  elements.importOrders.addEventListener("submit", importOrders);
}

async function init() {
  bindEvents();
  try {
    const health = await api.health();
    if (health.role !== "customer_service") throw new Error("当前端口不是客服入口");
  } catch (error) {
    showToast(elements.toasts, errorMessage(error), "error");
  }
  await Promise.all([loadConversations(), loadProducts(), loadOrders()]);
  window.setInterval(() => loadConversations({ silent: true }), 3000);
}

init();
