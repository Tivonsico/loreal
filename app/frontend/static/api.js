export class ApiError extends Error {
  constructor(message, status, details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

function describeDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join("；");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return "请求失败";
}

async function request(path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}) } };
  if (init.body && !(init.body instanceof FormData) && typeof init.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.body);
  }
  const response = await fetch(path, init);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail = payload?.detail ?? payload;
    throw new ApiError(describeDetail(detail), response.status, detail);
  }
  return payload;
}

function queryString(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      query.set(key, String(value).trim());
    }
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export const api = {
  health: () => request("/health"),
  listConversations: (params = {}) => request(`/api/v1/conversations${queryString(params)}`),
  createConversation: (payload) => request("/api/v1/conversations", { method: "POST", body: payload }),
  getConversation: (id) => request(`/api/v1/conversations/${encodeURIComponent(id)}`),
  listMessages: (id, params = {}) => request(
    `/api/v1/conversations/${encodeURIComponent(id)}/messages${queryString(params)}`,
  ),
  sendText: (id, content) => request(
    `/api/v1/conversations/${encodeURIComponent(id)}/messages/text`,
    { method: "POST", body: { content } },
  ),
  sendMedia: (id, file, messageType, caption = "") => {
    const form = new FormData();
    form.append("message_type", messageType);
    if (caption.trim()) form.append("caption", caption.trim());
    form.append("file", file);
    return request(`/api/v1/conversations/${encodeURIComponent(id)}/messages/media`, {
      method: "POST",
      body: form,
    });
  },
  listProducts: (params = {}) => request(`/api/v1/products${queryString(params)}`),
  createProduct: (payload) => request("/api/v1/products", { method: "POST", body: payload }),
  importProducts: (items) => request("/api/v1/products/import", {
    method: "POST",
    body: { items },
  }),
  listOrders: (params = {}) => request(`/api/v1/orders${queryString(params)}`),
  createOrder: (payload) => request("/api/v1/orders", { method: "POST", body: payload }),
  importOrders: (items) => request("/api/v1/orders/import", {
    method: "POST",
    body: { items },
  }),
  managementSummary: () => request("/api/v1/management/summary"),
  managementConversations: (params = {}) => request(
    `/api/v1/management/conversations${queryString(params)}`,
  ),
  conversationContext: (id) => request(
    `/api/v1/management/conversations/${encodeURIComponent(id)}/context`,
  ),
  conversationAssistance: (id) => request(
    `/api/v1/management/conversations/${encodeURIComponent(id)}/assistance`,
    { method: "POST" },
  ),
  searchMessages: (params = {}) => request(
    `/api/v1/management/messages/search${queryString(params)}`,
  ),
  managementOrders: (params = {}) => request(
    `/api/v1/management/orders${queryString(params)}`,
  ),
  managementOrder: (id) => request(`/api/v1/management/orders/${encodeURIComponent(id)}`),
  updateManagementOrder: (id, payload) => request(
    `/api/v1/management/orders/${encodeURIComponent(id)}`,
    { method: "PATCH", body: payload },
  ),
  managementProducts: (params = {}) => request(
    `/api/v1/management/products${queryString(params)}`,
  ),
  managementProduct: (id) => request(
    `/api/v1/management/products/${encodeURIComponent(id)}`,
  ),
  updateManagementProduct: (id, payload) => request(
    `/api/v1/management/products/${encodeURIComponent(id)}`,
    { method: "PATCH", body: payload },
  ),
  workOrders: (params = {}) => request(`/api/v1/work-orders${queryString(params)}`),
  workOrder: (id) => request(`/api/v1/work-orders/${encodeURIComponent(id)}`),
  createWorkOrder: (payload) => request("/api/v1/work-orders", { method: "POST", body: payload }),
  updateWorkOrderStatus: (id, payload) => request(
    `/api/v1/work-orders/${encodeURIComponent(id)}/status`,
    { method: "PATCH", body: payload },
  ),
  previewWorkbook: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/v1/imports/workbook/preview", { method: "POST", body: form });
  },
  commitWorkbook: (batchId) => request(
    `/api/v1/imports/workbook/${encodeURIComponent(batchId)}/commit`,
    { method: "POST" },
  ),
  publicAfterSales: (customerId) => request(
    `/api/v1/public/customers/${encodeURIComponent(customerId)}/after-sales`,
  ),
  publicConversationAfterSales: (conversationId) => request(
    `/api/v1/public/conversations/${encodeURIComponent(conversationId)}/after-sales`,
  ),
};

export class ConversationSocket {
  constructor({ onState, onMessage, onReady }) {
    this.onState = onState;
    this.onMessage = onMessage;
    this.onReady = onReady;
    this.socket = null;
    this.conversationId = null;
    this.reconnectTimer = null;
    this.attempt = 0;
    this.generation = 0;
  }

  connect(conversationId) {
    this.close();
    this.conversationId = conversationId;
    this.generation += 1;
    this.#open(this.generation);
  }

  #open(generation) {
    if (!this.conversationId || generation !== this.generation) return;
    this.onState?.("connecting");
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const path = `/ws/conversations/${encodeURIComponent(this.conversationId)}`;
    const socket = new WebSocket(`${scheme}://${window.location.host}${path}`);
    this.socket = socket;

    socket.addEventListener("open", () => {
      if (generation !== this.generation) return;
      this.attempt = 0;
      this.onState?.("connected");
    });
    socket.addEventListener("message", (event) => {
      if (generation !== this.generation) return;
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      if (payload.event === "connection.ready") this.onReady?.(payload.data);
      if (payload.event === "message.created") this.onMessage?.(payload.data);
    });
    socket.addEventListener("close", () => {
      if (generation !== this.generation || !this.conversationId) return;
      this.onState?.("disconnected");
      const delay = Math.min(8000, 800 * (2 ** this.attempt));
      this.attempt += 1;
      this.reconnectTimer = window.setTimeout(() => this.#open(generation), delay);
    });
    socket.addEventListener("error", () => {
      socket.close();
    });
  }

  close() {
    this.generation += 1;
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.conversationId = null;
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
    this.onState?.("idle");
  }
}
