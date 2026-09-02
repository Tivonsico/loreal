import { createIcon } from "./icons.js";

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : dateFormatter.format(date);
}

export function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(number)
    : String(value);
}

export function messageTypeForFile(file) {
  const mime = (file?.type || "").toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("audio/")) return "audio";
  if (mime.startsWith("video/")) return "video";
  return "file";
}

export function messageTypeLabel(messageType) {
  const labels = { image: "图片", audio: "音频", video: "视频", file: "文件" };
  return labels[messageType] || "文件";
}

export function orderStatusLabel(status) {
  const labels = {
    pending: "待处理",
    paid: "已付款",
    pending_shipment: "待发货",
    shipped: "已发货",
    delivered: "已签收",
    completed: "已完成",
    canceled: "已取消",
    cancelled: "已取消",
    refunded: "已退款",
    closed: "已关闭",
  };
  return labels[status] || status || "—";
}

export function pulseSpectrum() {
  document.body.classList.remove("is-message-pulse");
  void document.body.offsetWidth;
  document.body.classList.add("is-message-pulse");
  window.setTimeout(() => document.body.classList.remove("is-message-pulse"), 950);
}

export function setConnectionState(pill, textNode, state) {
  const labels = {
    idle: "尚未选择会话",
    connecting: "正在连接",
    connected: "实时连接已建立",
    disconnected: "连接中断，正在重试",
  };
  pill.dataset.connection = state;
  textNode.textContent = labels[state] || labels.idle;
  document.body.dataset.wsState = state;
}

function mediaElement(message) {
  if (!message.media_url) return null;
  let element;
  if (message.message_type === "image") {
    element = document.createElement("img");
    element.alt = message.original_filename || "聊天图片";
    element.loading = "lazy";
  } else if (message.message_type === "audio") {
    element = document.createElement("audio");
    element.controls = true;
    element.preload = "metadata";
  } else if (message.message_type === "video") {
    element = document.createElement("video");
    element.controls = true;
    element.preload = "metadata";
  } else {
    element = document.createElement("a");
    element.className = "file-message";
    element.href = message.media_url;
    element.target = "_blank";
    element.rel = "noreferrer";
    element.append(createIcon("file"));
    const label = document.createElement("span");
    label.textContent = message.original_filename || "打开文件";
    element.append(label);
    return element;
  }
  element.className = "message-media";
  element.src = message.media_url;
  return element;
}

function messageElement(message, currentRole) {
  const row = document.createElement("article");
  row.className = "message-row";
  row.dataset.messageId = String(message.id);
  if (message.sender_role === currentRole) row.classList.add("is-own");

  const author = document.createElement("div");
  author.className = "message-author";
  const role = document.createElement("span");
  const roleLabels = {
    customer_service: "客服",
    customer: "客户",
    system: "系统通知",
  };
  role.textContent = roleLabels[message.sender_role] || message.sender_role;
  if (message.sender_role === "system") row.classList.add("is-system");
  const time = document.createElement("time");
  time.dateTime = message.created_at || "";
  time.textContent = formatDate(message.created_at);
  author.append(role, time);

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  if (message.content) {
    const paragraph = document.createElement("p");
    paragraph.textContent = message.content;
    bubble.append(paragraph);
  }
  const media = mediaElement(message);
  if (media) bubble.append(media);
  row.append(author, bubble);
  return row;
}

export class MessageTimeline {
  constructor(container, currentRole) {
    this.container = container;
    this.currentRole = currentRole;
    this.ids = new Set();
  }

  reset(messages = []) {
    this.container.replaceChildren();
    this.ids.clear();
    messages.forEach((message) => this.add(message, { scroll: false, pulse: false }));
    if (!messages.length) this.#showEmpty();
    this.scrollToEnd();
  }

  add(message, { scroll = true, pulse = true } = {}) {
    if (this.ids.has(message.id)) return false;
    const empty = this.container.querySelector(".empty-compact");
    if (empty) empty.remove();
    this.ids.add(message.id);
    this.container.append(messageElement(message, this.currentRole));
    if (scroll) this.scrollToEnd();
    if (pulse) pulseSpectrum();
    return true;
  }

  #showEmpty() {
    const empty = document.createElement("div");
    empty.className = "empty-compact";
    empty.textContent = "当前会话还没有消息，可以发送第一条消息。";
    this.container.append(empty);
  }

  scrollToEnd() {
    window.requestAnimationFrame(() => {
      this.container.scrollTop = this.container.scrollHeight;
    });
  }
}

export function conversationButton(conversation, activeId) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "conversation-item";
  button.dataset.conversationId = conversation.id;
  if (conversation.id === activeId) button.classList.add("is-active");

  const title = document.createElement("span");
  title.className = "conversation-title";
  title.textContent = conversation.title || "未命名咨询";
  const meta = document.createElement("span");
  meta.className = "conversation-meta";
  const customer = document.createElement("span");
  customer.textContent = conversation.customer_id;
  const time = document.createElement("time");
  time.dateTime = conversation.updated_at || "";
  time.textContent = formatDate(conversation.updated_at);
  meta.append(customer, time);
  button.append(title, meta);
  return button;
}

export function productCard(product) {
  const card = document.createElement("article");
  card.className = "data-card";
  const title = document.createElement("h3");
  title.textContent = product.name;
  const description = document.createElement("p");
  description.textContent = product.description || "暂无商品描述";
  const meta = document.createElement("div");
  meta.className = "data-card-meta";
  const id = document.createElement("span");
  id.textContent = product.external_id;
  const price = document.createElement("strong");
  price.className = "data-price";
  price.textContent = formatMoney(product.price);
  meta.append(id, price);
  card.append(title, description, meta);
  return card;
}

export function orderCard(order) {
  const card = document.createElement("article");
  card.className = "data-card";
  const title = document.createElement("h3");
  title.textContent = order.external_id;
  const summary = document.createElement("p");
  const product = order.product_external_id ? `商品 ${order.product_external_id}` : "未关联商品";
  summary.textContent = `${product} · 数量 ${order.quantity}`;
  const meta = document.createElement("div");
  meta.className = "data-card-meta";
  const status = document.createElement("span");
  status.textContent = orderStatusLabel(order.status);
  const amount = document.createElement("strong");
  amount.className = "data-price";
  amount.textContent = formatMoney(order.total_amount);
  meta.append(status, amount);
  card.append(title, summary, meta);
  return card;
}

export function renderCollection(container, items, renderer, emptyText) {
  container.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-compact";
    empty.textContent = emptyText;
    container.append(empty);
    return;
  }
  items.forEach((item) => container.append(renderer(item)));
}

export function showToast(region, message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast${type === "error" ? " is-error" : ""}`;
  toast.textContent = message;
  region.append(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

export function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(150, textarea.scrollHeight)}px`;
}

export function parseJsonInput(value, label) {
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`${label}不是有效 JSON`);
  }
}

export function normalizedItemsPayload(value, label) {
  const parsed = parseJsonInput(value, label);
  const items = Array.isArray(parsed) ? parsed : parsed?.items;
  if (!Array.isArray(items) || !items.length) {
    throw new Error(`${label}必须包含至少一条 items 数据`);
  }
  return items;
}
