from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.backend.agent import ASSISTANCE_AGENT_NAME, create_agent_registry
from app.backend.agent.context import stable_context_fingerprint
from app.backend.agent.customer_service_assistance import CustomerServiceAssistanceAgent
from app.backend.agent.openai_compatible_provider import (
    EmotionBatchAdvice,
    ModelAdvice,
    OpenAICompatibleChatProvider,
)
from app.backend.models import (
    Conversation,
    Message,
    Order,
    Product,
    RealtimeEvent,
    WorkOrder,
)


def test_stable_context_fingerprint_ignores_capture_time_and_prior_hash() -> None:
    first = {
        "schema": "customer-service-context.v1",
        "snapshot": {
            "captured_at": "2026-01-01T00:00:00Z",
            "fingerprint": "old",
            "message_count": 1,
        },
        "chat": {"messages": [{"id": 1, "sender_role": "customer", "content": "你好"}]},
    }
    second = {
        **first,
        "snapshot": {
            "captured_at": "2026-09-03T00:00:00Z",
            "fingerprint": "new",
            "message_count": 1,
        },
    }

    assert stable_context_fingerprint(first) == stable_context_fingerprint(second)
    second["chat"] = {"messages": [{"id": 1, "sender_role": "customer", "content": "退款"}]}
    assert stable_context_fingerprint(first) != stable_context_fingerprint(second)


def test_emotion_batch_uses_disabled_thinking_and_filters_evidence(monkeypatch) -> None:
    captured: dict = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            content = {
                "items": [
                    {
                        "conversation_id": "conv-1",
                        "emotion": "anxious",
                        "confidence": 0.91,
                        "risk_type": "emotion_escalation",
                        "severity": "high",
                        "summary": "客户担心退款迟迟未到账。",
                        "evidence_message_ids": [1, 999],
                    }
                ]
            }
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("app.backend.agent.openai_compatible_provider.urlopen", fake_urlopen)
    provider = OpenAICompatibleChatProvider(
        "key",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-5.3-flash",
        5,
        reasoning_mode="disabled",
    )

    results = provider.classify_emotions(
        [
            {
                "conversation_id": "conv-1",
                "messages": [
                    {"id": 1, "sender_role": "customer", "content": "退款怎么还没到"},
                    {"id": 2, "sender_role": "customer_service", "content": "正在查询"},
                ],
                "masked_account": "不应离开边界",
            }
        ]
    )

    assert results == [
        EmotionBatchAdvice(
            conversation_id="conv-1",
            emotion="anxious",
            confidence=0.91,
            risk_type="emotion_escalation",
            severity="high",
            summary="客户担心退款迟迟未到账。",
            evidence_message_ids=[1],
        )
    ]
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured["payload"]
    assert captured["payload"]["max_tokens"] == 1800
    assert "masked_account" not in captured["payload"]["messages"][-1]["content"]


def test_emotion_batch_retries_once_without_optional_reasoning_fields(monkeypatch) -> None:
    payloads: list[dict] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            content = {
                "items": [
                    {
                        "conversation_id": "conv-1",
                        "emotion": "neutral",
                        "confidence": 0.8,
                        "summary": "客户正在普通咨询。",
                    }
                ]
            }
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data))
        if len(payloads) == 1:
            raise HTTPError(
                request.full_url,
                400,
                "bad request",
                {},
                BytesIO(b'{"error":"unsupported parameter: thinking"}'),
            )
        return Response()

    monkeypatch.setattr("app.backend.agent.openai_compatible_provider.urlopen", fake_urlopen)
    provider = OpenAICompatibleChatProvider(
        "key", "https://open.bigmodel.cn/api/paas/v4", "glm", 5
    )

    result = provider.classify_emotions(
        [
            {
                "conversation_id": "conv-1",
                "messages": [{"id": 1, "sender_role": "customer", "content": "查订单"}],
            }
        ]
    )

    assert result[0].conversation_id == "conv-1"
    assert len(payloads) == 2
    assert payloads[0]["thinking"] == {"type": "disabled"}
    assert all(key not in payloads[1] for key in ("thinking", "reasoning_effort", "max_tokens"))


def _seed_assistance_conversation(app, *, with_business_records: bool = True) -> str:
    conversation_id = "conv-assistance"
    with app.state.session_factory() as db:
        db.add(
            Conversation(
                id=conversation_id,
                source_external_id="CHAT-AI-001",
                customer_id="customer-ai",
                buyer_nickname="小夏",
                title="查询物流进度",
            )
        )
        db.flush()
        if with_business_records:
            db.add(
                Product(
                    external_id="SKU-AI-001",
                    sku="SKU-AI-001",
                    name="复颜玻尿酸水光充盈导入乳霜",
                    brand="L'Oréal Paris",
                    price=329,
                )
            )
            db.flush()
            db.add(
                Order(
                    external_id="ORDER-AI-001",
                    customer_id="customer-ai",
                    conversation_id=conversation_id,
                    product_external_id="SKU-AI-001",
                    product_name="复颜玻尿酸水光充盈导入乳霜",
                    status="已发货",
                    quantity=1,
                    total_amount=329,
                    logistics_company="顺丰",
                    logistics_no="SF123456",
                )
            )
            db.flush()
            db.add(
                WorkOrder(
                    external_id="WO-AI-001",
                    ticket_type="logistics",
                    conversation_id=conversation_id,
                    order_external_id="ORDER-AI-001",
                    customer_id="customer-ai",
                    status="processing",
                    description="客户查询物流停滞",
                )
            )
            db.flush()
        db.add_all(
            [
                Message(
                    conversation_id=conversation_id,
                    sender_role="customer",
                    sequence_no=1,
                    message_type="text",
                    content="我的快递为什么还没到，麻烦帮我查一下物流。",
                    related_order_external_id=("ORDER-AI-001" if with_business_records else None),
                    related_work_order_external_id=("WO-AI-001" if with_business_records else None),
                ),
                Message(
                    conversation_id=conversation_id,
                    sender_role="customer_service",
                    sequence_no=2,
                    message_type="text",
                    content="我先为您核实。",
                ),
            ]
        )
        db.commit()
    return conversation_id


def _database_snapshot(app, conversation_id: str) -> tuple:
    with app.state.session_factory() as db:
        conversation = db.get(Conversation, conversation_id)
        return (
            db.scalar(select(func.count()).select_from(Message)),
            db.scalar(select(func.count()).select_from(RealtimeEvent)),
            db.scalar(select(func.count()).select_from(Order)),
            db.scalar(select(func.count()).select_from(WorkOrder)),
            conversation.updated_at,
        )


def test_default_registry_is_explicit_registered_and_frozen() -> None:
    registry = create_agent_registry()

    assert registry.names() == (ASSISTANCE_AGENT_NAME,)
    assert registry.frozen is True
    assert registry.get(ASSISTANCE_AGENT_NAME).version == "1.3"

    try:
        registry.register(CustomerServiceAssistanceAgent())
    except RuntimeError as error:
        assert "冻结" in str(error)
    else:
        raise AssertionError("冻结后的注册表不应接受新 Agent")


def test_assistance_agent_uses_valid_online_provider_and_degrades_safely() -> None:
    context = {
        "snapshot": {
            "captured_at": "2026-08-11T09:00:00+00:00",
            "last_message_id": 7,
            "message_count": 1,
            "fingerprint": "abc",
        },
        "chat": {"messages": [{"id": 7, "sender_role": "customer", "content": "物流什么时候到"}]},
        "order": {"status": "not_linked", "record": None},
        "product": {"status": "not_linked", "record": None},
        "work_order": {"status": "not_linked", "record": None},
        "reply_handbook": {"status": "source_unavailable", "candidates": []},
    }

    class OnlineProvider:
        def generate(self, _context):
            return ModelAdvice(
                intent="物流查询",
                summary="客户希望确认送达时间。",
                service_handling="客服正在核对关联订单和物流记录。",
                current_status="等待补充订单信息后继续处理。",
                urgency="medium",
                risks=["订单尚未关联"],
                next_actions=["先确认订单号"],
                suggested_reply="请提供订单号，我马上为您核实。",
                evidence_message_ids=[7],
            )

    class BrokenProvider:
        def generate(self, _context):
            raise RuntimeError("provider down")

    online = CustomerServiceAssistanceAgent(OnlineProvider()).run(context)
    degraded = CustomerServiceAssistanceAgent(BrokenProvider()).run(context)

    assert online.mode == "online"
    assert online.intent == "物流查询"
    assert online.degraded_reason is None
    assert degraded.mode == "offline"
    assert degraded.degraded_reason == "在线模型暂时不可用，已使用完整会话离线分析"


def test_offline_fallback_uses_complete_chat_and_recognizes_resolved_acknowledgement() -> None:
    context = {
        "snapshot": {
            "captured_at": "2026-08-11T09:00:00+00:00",
            "last_message_id": 4,
            "message_count": 4,
            "fingerprint": "complete-chat",
        },
        "chat": {
            "messages": [
                {
                    "id": 1,
                    "sender_role": "customer",
                    "content": "退货后退款一直没到账，麻烦帮我核实。",
                },
                {
                    "id": 2,
                    "sender_role": "customer_service",
                    "content": "已经查到退款工单，当前正在处理中。",
                },
                {
                    "id": 3,
                    "sender_role": "customer_service",
                    "content": "款项预计今天原路退回，请留意到账通知。",
                },
                {
                    "id": 4,
                    "sender_role": "customer",
                    "content": "好的好的，谢谢你，帮大忙了。",
                },
            ]
        },
        "order": {"status": "present", "record": {"external_id": "ORDER-1"}},
        "product": {"status": "not_linked", "record": None},
        "work_order": {
            "status": "present",
            "record": {
                "external_id": "WO-1",
                "status": "processing",
                "description": "退款未到账",
                "resolution": "原路退回",
            },
        },
        "reply_handbook": {"status": "source_unavailable", "candidates": []},
    }

    result = CustomerServiceAssistanceAgent().run(context)

    assert "退款" in result.summary
    assert "客户也确认了" in result.summary
    source_sentences = [item["content"] for item in context["chat"]["messages"]]
    generated_analysis = " ".join(
        [result.intent, result.summary, result.service_handling, result.current_status]
    )
    assert all(sentence not in generated_analysis for sentence in source_sentences)
    assert "客服已" in result.service_handling
    assert "客户已" in result.current_status
    assert all("确认客户本轮" not in action for action in result.next_actions)
    assert "不客气" in result.suggested_reply
    assert all("话术" not in risk for risk in result.risks)

    class NoNewIntentProvider:
        def generate(self, _context):
            return ModelAdvice(
                intent="无新诉求",
                summary="退款问题已经说明。",
                service_handling="客服已经提交退款申请。",
                current_status="等待退款到账。",
                urgency="normal",
                risks=[],
                next_actions=["跟进到账结果"],
                suggested_reply="退款申请已经提交，请留意到账通知。",
                evidence_message_ids=[1, 4],
            )

    online = CustomerServiceAssistanceAgent(NoNewIntentProvider()).run(context)
    assert online.mode == "online"
    assert "退款没到账" in online.intent
    assert "无新诉求" not in online.intent


def test_model_prompt_requires_complete_transcript_and_handbook_is_optional(monkeypatch) -> None:
    captured: dict = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            content = {
                "intent": "客户想确认退款进度，客服已处理完毕并致谢",
                "summary": "客户在等退款到账。客服祝客户生活愉快。",
                "service_handling": "客服已核验退款记录并告知预计到账时间。最后祝客户生活愉快。",
                "current_status": "等待退款到账，客户表示感谢",
                "urgency": "一般",
                "risks": "无额外风险",
                "next_actions": "礼貌收尾，不要重复追问",
                "suggested_reply": "",
                "evidence_message_ids": [1, 4],
                "unused_field": "应被安全忽略",
            }
            fenced = f"```json\n{json.dumps(content, ensure_ascii=False)}\n```"
            return json.dumps({"choices": [{"message": {"content": fenced}}]}).encode()

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr("app.backend.agent.openai_compatible_provider.urlopen", fake_urlopen)
    context = {
        "chat": {
            "messages": [
                {"id": 1, "sender_role": "customer", "content": "退款还没到账"},
                {"id": 2, "sender_role": "customer_service", "content": "预计今天原路退回"},
                {"id": 4, "sender_role": "customer", "content": "好的，谢谢"},
            ]
        },
        "reply_handbook": {"status": "source_unavailable", "candidates": []},
    }

    advice = OpenAICompatibleChatProvider(
        "test-key", "https://example.test/v1", "test-model", 5
    ).generate(context)

    prompt = captured["payload"]["messages"]
    assert all(
        message["content"] in prompt[-1]["content"] for message in context["chat"]["messages"]
    )
    assert "按时间顺序阅读完整聊天" in prompt[0]["content"]
    assert "先在内部提取七类信息" in prompt[0]["content"]
    assert "只写整段聊天的核心问题" in prompt[0]["content"]
    assert "每句话只表达一个重点" in prompt[0]["content"]
    assert "复杂内容拆成短句" in prompt[0]["content"]
    assert "不能漏掉关键事实" in prompt[0]["content"]
    assert "三组用户事实与标准 JSON 示例" in prompt[0]["content"]
    assert [message["role"] for message in prompt[1:7]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert "售后期已经过了" in prompt[2]["content"]
    assert "包裹几天没动" in prompt[4]["content"]
    assert "脸上不舒服" in prompt[6]["content"]
    assert captured["payload"]["model"] == "test-model"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert "enable_thinking" not in captured["payload"]
    assert "thinking" not in captured["payload"]
    assert "reasoning_effort" not in captured["payload"]
    assert "max_tokens" not in captured["payload"]
    assert advice.suggested_reply.startswith("好的")
    assert advice.urgency == "normal"
    assert advice.next_actions == ["礼貌收尾，不要重复追问"]
    assert advice.intent == "客户想确认退款进度"
    assert "生活愉快" not in advice.summary
    assert "生活愉快" not in advice.service_handling
    assert "感谢" not in advice.current_status
    assert advice.summary == "客户在等退款到账。"
    assert advice.service_handling.endswith("。")
    assert advice.current_status == "等待退款到账。"

    mixed = OpenAICompatibleChatProvider._remove_low_signal_clauses(
        "客户确认退款10元并致谢。客服祝客户生活愉快。",
        sentence_style=True,
    )
    assert mixed == "客户确认退款10元并致谢。"

    natural = OpenAICompatibleChatProvider._remove_low_signal_clauses(
        "客服核实退货已经入库了，确认给客户走线下渠道退款10元。",
        sentence_style=True,
    )
    assert natural == "客服核实退货已经入库了，确认给客户走线下渠道退款10元。"
    assert not hasattr(OpenAICompatibleChatProvider, "_conversational_business_text")

    OpenAICompatibleChatProvider(
        "test-key",
        "https://example.test/v1",
        "another-model",
        5,
        json_mode=False,
    ).generate(context)
    assert captured["payload"]["model"] == "another-model"
    assert "response_format" not in captured["payload"]

    OpenAICompatibleChatProvider(
        "test-key",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-5.3-flash",
        5,
    ).generate(context)
    assert captured["payload"]["thinking"] == {"type": "enabled"}
    assert captured["payload"]["reasoning_effort"] == "low"
    assert captured["payload"]["max_tokens"] == 1200


def test_service_assistance_verifies_facts_without_writing_database(app_pair) -> None:
    customer_app, service_app = app_pair
    with TestClient(service_app) as service:
        conversation_id = _seed_assistance_conversation(service_app)
        before = _database_snapshot(service_app, conversation_id)

        response = service.post(f"/api/v1/management/conversations/{conversation_id}/assistance")

        assert response.status_code == 200
        body = response.json()
        assert body["agent_name"] == ASSISTANCE_AGENT_NAME
        assert body["mode"] == "offline"
        assert body["intent"] == "订单与物流查询"
        assert body["basis_message_count"] == 2
        assert body["basis_last_message_id"] > 0
        assert body["snapshot_fingerprint"]
        assert body["evidence_message_ids"]
        assert body["service_handling"]
        assert body["current_status"]
        assert "SF123456" in body["suggested_reply"]
        facts = {item["label"]: item for item in body["facts"]}
        assert facts["订单"]["status"] == "present"
        assert facts["商品"]["status"] == "present"
        assert facts["售后"]["status"] == "present"
        assert facts["回复手册"]["status"] == "source_unavailable"
        assert _database_snapshot(service_app, conversation_id) == before

    with TestClient(customer_app) as customer:
        forbidden = customer.post(f"/api/v1/management/conversations/{conversation_id}/assistance")
        assert forbidden.status_code == 403


def test_assistance_distinguishes_empty_business_sections(app_pair) -> None:
    _, service_app = app_pair
    with TestClient(service_app) as client:
        conversation_id = _seed_assistance_conversation(service_app, with_business_records=False)
        response = client.post(f"/api/v1/management/conversations/{conversation_id}/assistance")

    assert response.status_code == 200
    facts = {item["label"]: item for item in response.json()["facts"]}
    assert facts["订单"]["status"] == "not_linked"
    assert facts["商品"]["status"] == "not_linked"
    assert facts["售后"]["status"] == "not_linked"
    assert "提供订单号" in "".join(response.json()["next_actions"])


def test_assistance_returns_404_before_running_agent(app_pair) -> None:
    _, service_app = app_pair
    with TestClient(service_app) as client:
        response = client.post("/api/v1/management/conversations/missing/assistance")

    assert response.status_code == 404
