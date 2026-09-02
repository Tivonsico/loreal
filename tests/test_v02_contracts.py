from datetime import UTC, datetime

from app.backend.schemas import MessageOut, WorkOrderOut


def test_imported_system_message_is_a_valid_read_contract() -> None:
    message = MessageOut(
        id=1,
        source_external_id="MSG-001",
        conversation_id="CONV-001",
        sender_role="system",
        sequence_no=1,
        message_type="text",
        content="订单已发货",
        media_url=None,
        original_filename=None,
        mime_type=None,
        size_bytes=None,
        created_at=datetime.now(UTC),
    )

    assert message.sender_role == "system"
    assert message.content == "订单已发货"


def test_work_order_output_accepts_orm_style_attributes() -> None:
    class WorkOrderRecord:
        id = 1
        external_id = "WO-001"
        ticket_type = "logistics"
        conversation_id = "CONV-001"
        order_external_id = "ORDER-001"
        customer_id = "buyer-001"
        buyer_nickname = "小雅"
        status = "pending"
        source_status = "待处理"
        assignee = "客服小欧"
        description = "物流停滞"
        resolution = None
        opened_at = None
        closed_at = None
        source_extra = {}
        created_at = datetime.now(UTC)
        updated_at = datetime.now(UTC)

    result = WorkOrderOut.model_validate(WorkOrderRecord())

    assert result.external_id == "WO-001"
    assert result.ticket_type == "logistics"
