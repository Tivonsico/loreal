from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["customer", "customer_service", "system"]
MessageType = Literal["text", "image", "audio", "video", "file"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(ORMModel):
    id: str
    source_external_id: str | None = None
    customer_id: str
    buyer_nickname: str | None = None
    title: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ProductInput(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    sku: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    extra: dict[str, Any] = Field(default_factory=dict)


class ProductOut(ORMModel):
    id: int
    external_id: str
    sku: str | None
    name: str
    brand: str | None
    description: str | None
    price: Decimal | None
    extra: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class OrderInput(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(min_length=1, max_length=100)
    buyer_nickname: str | None = Field(default=None, max_length=100)
    product_external_id: str | None = Field(default=None, max_length=100)
    conversation_id: str | None = None
    status: str = Field(default="unknown", min_length=1, max_length=50)
    quantity: int = Field(default=1, ge=1)
    total_amount: Decimal | None = Field(default=None, ge=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    product_name: str | None = Field(default=None, max_length=300)
    logistics_company: str | None = Field(default=None, max_length=100)
    logistics_no: str | None = Field(default=None, max_length=100)
    ordered_at: datetime | None = None
    paid_at: datetime | None = None
    payment_stage: str | None = Field(default=None, max_length=30)
    shipped_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class OrderOut(ORMModel):
    id: int
    external_id: str
    customer_id: str
    buyer_nickname: str | None = None
    product_external_id: str | None
    conversation_id: str | None
    status: str
    quantity: int
    total_amount: Decimal | None
    unit_price: Decimal | None = None
    product_name: str | None = None
    logistics_company: str | None = None
    logistics_no: str | None = None
    ordered_at: datetime | None = None
    paid_at: datetime | None = None
    payment_stage: str | None = None
    shipped_at: datetime | None = None
    extra: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ImportProductsRequest(BaseModel):
    items: list[ProductInput] = Field(min_length=1, max_length=5000)


class ImportOrdersRequest(BaseModel):
    items: list[OrderInput] = Field(min_length=1, max_length=5000)


class ImportResult(BaseModel):
    created: int
    updated: int


class TextMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def reject_whitespace_only(self) -> TextMessageCreate:
        self.content = self.content.strip()
        if not self.content:
            raise ValueError("消息正文不能为空")
        return self


class MessageOut(ORMModel):
    id: int
    source_external_id: str | None = None
    conversation_id: str
    sender_role: Role
    sequence_no: int | None = None
    message_type: MessageType
    content: str | None
    raw_content: str | None = None
    related_order_external_id: str | None = None
    related_work_order_external_id: str | None = None
    media_url: str | None
    original_filename: str | None
    mime_type: str | None
    size_bytes: int | None
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageOut]
    next_before_id: int | None


WorkOrderType = Literal[
    "replacement_exchange",
    "offline_payment",
    "logistics",
    "adverse_reaction",
    "after_sale_return",
]
WorkOrderStatus = Literal["pending", "processing", "completed"]


class WorkOrderBase(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    ticket_type: WorkOrderType
    conversation_id: str | None = None
    order_external_id: str | None = Field(default=None, max_length=100)
    customer_id: str | None = Field(default=None, max_length=100)
    buyer_nickname: str | None = Field(default=None, max_length=100)
    status: WorkOrderStatus = "pending"
    source_status: str | None = Field(default=None, max_length=50)
    assignee: str | None = Field(default=None, max_length=100)
    description: str | None = None
    resolution: str | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    source_extra: dict[str, Any] = Field(default_factory=dict)


class WorkOrderOut(WorkOrderBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class WorkOrderStatusUpdate(BaseModel):
    status: WorkOrderStatus
    note: str = Field(min_length=1, max_length=2000)


class PublicAfterSalesOut(BaseModel):
    external_id: str
    ticket_type: WorkOrderType
    status: WorkOrderStatus
    updated_at: datetime
    replacement_tracking_no: str | None = None
    confirmed_payment_amount: Decimal | None = None
    confirmed_payment_status: str | None = None


class WorkbookImportError(BaseModel):
    sheet_name: str
    row_number: int
    column_name: str | None = None
    error_code: str
    message: str


class WorkbookPreviewOut(BaseModel):
    batch_id: str
    filename: str
    file_sha256: str
    status: Literal["ready", "invalid", "committed"]
    can_commit: bool
    sheets: dict[str, int]
    work_order_types: dict[str, int]
    error_count: int
    errors: list[WorkbookImportError]


class WorkbookCommitOut(BaseModel):
    batch_id: str
    status: Literal["committed"]
    created: dict[str, int]
    committed_at: datetime


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


class ManagementOrderOut(OrderOut):
    work_order_external_id: str | None = None


class ManagementOrderPage(PageMeta):
    items: list[ManagementOrderOut]


class OrderUpdate(BaseModel):
    status: str | None = Field(default=None, min_length=1, max_length=50)
    logistics_company: str | None = Field(default=None, max_length=100)
    logistics_no: str | None = Field(default=None, max_length=100)


class ManagementProductPage(PageMeta):
    items: list[ProductOut]


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)


class WorkOrderStatusLogOut(ORMModel):
    id: int
    from_status: str | None
    to_status: str
    note: str | None
    actor: str | None
    created_at: datetime


class WorkOrderDetailOut(WorkOrderOut):
    detail: dict[str, Any] = Field(default_factory=dict)
    status_logs: list[WorkOrderStatusLogOut] = Field(default_factory=list)


class WorkOrderCreate(WorkOrderBase):
    detail: dict[str, Any] = Field(default_factory=dict)


class WorkOrderPage(PageMeta):
    items: list[WorkOrderDetailOut]


class ConversationManagementOut(ConversationOut):
    order_external_id: str | None = None
    work_order_external_id: str | None = None
    work_order_type: WorkOrderType | None = None
    work_order_status: WorkOrderStatus | None = None


class ConversationManagementPage(PageMeta):
    items: list[ConversationManagementOut]


class ConversationContextOut(BaseModel):
    conversation: ConversationOut
    order: ManagementOrderOut | None = None
    product: ProductOut | None = None
    work_order: WorkOrderDetailOut | None = None


AssistanceFactStatus = Literal[
    "present",
    "not_linked",
    "referenced_not_found",
    "conflict",
    "filtered",
    "source_unavailable",
]


class AssistanceFactOut(BaseModel):
    label: str
    status: AssistanceFactStatus
    summary: str


EmotionLabel = Literal["positive", "neutral", "anxious", "angry", "sad"]


class TrailSummaryOut(BaseModel):
    """One trail node's one-sentence outcome; title matches the node it describes."""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    summary: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"title": "", "summary": value}
        return value


class AssistanceAnalysisOut(BaseModel):
    agent_name: str
    agent_version: str
    mode: Literal["offline", "online"]
    analyzed_at: datetime
    basis_last_message_id: int | None
    basis_message_count: int
    snapshot_fingerprint: str
    intent: str
    intent_confidence: float = Field(default=0.5, ge=0, le=1)
    summary: str
    service_handling: str
    current_status: str
    urgency: Literal["normal", "medium", "high"]
    facts: list[AssistanceFactOut]
    risks: list[str]
    next_actions: list[str]
    suggested_reply: str
    evidence_message_ids: list[int]
    playbook_status: Literal["source_unavailable", "no_match", "present", "truncated"]
    degraded_reason: str | None = None
    emotion: EmotionLabel = "neutral"
    emotion_confidence: float = Field(default=0.5, ge=0, le=1)
    customer_tags: list[str] = Field(default_factory=list, max_length=4)
    trail_summaries: list[TrailSummaryOut] = Field(default_factory=list, max_length=4)


EmotionRiskType = Literal[
    "none", "emotion_escalation", "repeat_contact", "repeat_refund", "complaint"
]
EmotionSeverity = Literal["low", "medium", "high"]


class EmotionAnalysisResultOut(BaseModel):
    conversation_id: str
    emotion: EmotionLabel
    confidence: float = Field(ge=0, le=1)
    risk_type: EmotionRiskType = "none"
    severity: EmotionSeverity = "low"
    summary: str = Field(min_length=1, max_length=120)
    evidence_message_ids: list[int] = Field(default_factory=list, max_length=5)


class EmotionAnalysisRunOut(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "partial_failed", "failed"]
    total_count: int = Field(ge=0)
    processed_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SourceReferenceOut(BaseModel):
    source_type: Literal["conversation", "message", "order", "work_order", "status_log"]
    source_id: str


class ServiceTrailNodeOut(BaseModel):
    kind: Literal["order_created", "consultation", "work_order_opened", "work_order_closed"]
    occurred_at: datetime
    title: str
    detail: str | None = None
    source_ref: SourceReferenceOut


class CustomerPanoramaOut(BaseModel):
    conversation_id: str
    customer_id: str
    buyer_nickname: str | None = None
    region: str | None = None
    recorded_paid_amount: Decimal
    order_count: int = Field(ge=0)
    consultation_count_30d: int = Field(ge=0)
    after_sales_count: int = Field(ge=0)
    latest_order_at: datetime | None = None
    fact_tags: list[str] = Field(default_factory=list, max_length=4)
    service_trail: list[ServiceTrailNodeOut] = Field(default_factory=list, max_length=4)


class EmotionTrendPointOut(BaseModel):
    date: str
    warning_count: int = Field(ge=0)


class EmotionDashboardOut(BaseModel):
    warning_count: int = Field(ge=0)
    high_risk_count: int = Field(ge=0)
    analyzed_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    closure_rate: float = Field(ge=0, le=1)
    trend: list[EmotionTrendPointOut]


class EmotionAnalysisListItemOut(EmotionAnalysisResultOut):
    buyer_nickname: str | None = None
    updated_at: datetime
    analyzed_at: datetime | None = None
    status: str
    assignee: str | None = None


class EmotionAnalysisPageOut(PageMeta):
    items: list[EmotionAnalysisListItemOut]


class MessageSearchItem(MessageOut):
    buyer_nickname: str | None = None
    conversation_source_external_id: str | None = None


class MessageSearchPage(PageMeta):
    items: list[MessageSearchItem]


class ManagementSummaryOut(BaseModel):
    conversations: int
    orders: int
    products: int
    work_orders: int
    pending_work_orders: int
    work_orders_by_type: dict[str, int]
