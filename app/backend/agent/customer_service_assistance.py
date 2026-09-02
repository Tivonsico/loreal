from __future__ import annotations

from typing import Any, Protocol

from app.backend.agent.openai_compatible_provider import OpenAICompatibleProviderError
from app.backend.schemas import AssistanceAnalysisOut, AssistanceFactOut


class AdviceProvider(Protocol):
    def generate(self, context: dict[str, Any]) -> Any: ...


class CustomerServiceAssistanceAgent:
    name = "customer_service_assistance"
    version = "1.3"

    def __init__(self, provider: AdviceProvider | None = None) -> None:
        self._provider = provider

    def run(self, context: dict[str, Any]) -> AssistanceAnalysisOut:
        offline = self._run_offline(context)
        if self._provider is None:
            return offline
        try:
            advice = self._provider.generate(context)
        except OpenAICompatibleProviderError as error:
            return offline.model_copy(
                update={"degraded_reason": f"{error}，已使用完整会话离线分析"}
            )
        except Exception:
            return offline.model_copy(
                update={"degraded_reason": "在线模型暂时不可用，已使用完整会话离线分析"}
            )
        return offline.model_copy(
            update={
                "mode": "online",
                "intent": self._prefer_complete_intent(advice.intent, offline.intent),
                "summary": advice.summary,
                "service_handling": advice.service_handling,
                "current_status": advice.current_status,
                "urgency": advice.urgency,
                "risks": advice.risks,
                "next_actions": advice.next_actions,
                "suggested_reply": advice.suggested_reply,
                "evidence_message_ids": advice.evidence_message_ids,
                "degraded_reason": None,
            }
        )

    def _run_offline(self, context: dict[str, Any]) -> AssistanceAnalysisOut:
        messages = context["chat"]["messages"]
        customer_messages = [m for m in messages if m["sender_role"] == "customer"]
        latest = customer_messages[-1]["content"] if customer_messages else ""
        acknowledged = self._is_acknowledgement(latest)
        issue_message = next(
            (
                item["content"]
                for item in reversed(customer_messages)
                if not self._is_acknowledgement(item["content"])
            ),
            latest,
        )
        combined = " ".join(item["content"] for item in customer_messages)
        intent, urgency = self._classify(combined)
        intent = self._complete_intent(intent, combined, context)
        facts = [
            self._fact("订单", context["order"]),
            self._fact("商品", context["product"]),
            self._fact("售后", context["work_order"]),
            AssistanceFactOut(
                label="回复手册",
                status=context["reply_handbook"]["status"],
                summary="资料源尚未配置，以下回复为一般服务建议",
            ),
        ]
        risks: list[str] = []
        if context["order"]["status"] in {"conflict", "filtered", "referenced_not_found"}:
            risks.append("订单引用未完成可信核验，回复前请核对订单号")
        if "不良反应" in intent or any(key in combined for key in ("过敏", "红肿", "刺痛")):
            risks.append("涉及肌肤不适，不应给出诊断或继续使用建议")
        service_handling = self._service_handling(context)
        current_status = self._current_status(context, acknowledged)
        next_actions = self._next_actions(intent, context, acknowledged)
        reply = self._suggested_reply(issue_message, intent, context, acknowledged)
        return AssistanceAnalysisOut(
            agent_name=self.name,
            agent_version=self.version,
            mode="offline",
            analyzed_at=context["snapshot"]["captured_at"],
            basis_last_message_id=context["snapshot"]["last_message_id"],
            basis_message_count=context["snapshot"]["message_count"],
            snapshot_fingerprint=context["snapshot"]["fingerprint"],
            intent=intent,
            summary=self._summary(intent, context, acknowledged),
            service_handling=service_handling,
            current_status=current_status,
            urgency=urgency,
            facts=facts,
            risks=risks,
            next_actions=next_actions,
            suggested_reply=reply,
            evidence_message_ids=[item["id"] for item in customer_messages[-3:]],
            playbook_status=context["reply_handbook"]["status"],
            degraded_reason=None,
        )


    @staticmethod
    def _is_acknowledgement(content: str) -> bool:
        compact = "".join(content.split()).strip("。！!，,~～")
        if not compact or len(compact) > 40 or any(mark in compact for mark in ("?", "？")):
            return False
        acknowledgement_words = ("谢谢", "感谢", "帮大忙", "好的", "好嘞", "明白", "收到")
        issue_words = ("退款", "退货", "换货", "物流", "快递", "过敏", "红肿", "刺痛", "没到账")
        return any(word in compact for word in acknowledgement_words) and not any(
            word in compact for word in issue_words
        )

    @staticmethod
    def _classify(content: str) -> tuple[str, str]:
        if any(key in content for key in ("过敏", "红肿", "刺痛", "不舒服")):
            return "肌肤不适与安全咨询", "high"
        if any(key in content for key in ("退款", "退货", "换货", "售后", "用不惯", "寄回")):
            return "售后处理咨询", "medium"
        if any(key in content for key in ("物流", "快递", "发货", "到货")):
            return "订单与物流查询", "medium"
        if any(key in content for key in ("怎么用", "适合", "成分", "商品")):
            return "商品使用咨询", "normal"
        return "一般服务咨询", "normal"

    @staticmethod
    def _complete_intent(
        intent: str,
        content: str,
        context: dict[str, Any],
    ) -> str:
        work_order = context["work_order"].get("record") or {}
        ticket_type = work_order.get("ticket_type")
        if ticket_type == "offline_payment" or "退款" in content:
            if "售后期" in content or "售后单关闭" in content:
                return "客户把货退回去了，但是售后期已经过了，没法退款，希望能走线下渠道把钱退回来"
            return "客户退了货，但退款没到账，想尽快拿到退款"
        if ticket_type == "after_sale_return" or any(
            key in content for key in ("退货", "用不惯", "寄回")
        ):
            return "产品用着不合适，客户想退货退款"
        return intent

    @staticmethod
    def _prefer_complete_intent(model_intent: str, fallback_intent: str) -> str:
        low_information = ("无新诉求", "暂无新诉求", "无明确诉求", "客户致谢", "问题已解决")
        if any(term in model_intent for term in low_information):
            return fallback_intent
        return model_intent

    @staticmethod
    def _fact(label: str, section: dict[str, Any]) -> AssistanceFactOut:
        status = section["status"]
        record = section.get("record") or {}
        if status == "present":
            identity = record.get("external_id") or record.get("name") or "已关联"
            summary = f"已核验 {identity}"
        elif status == "not_linked":
            summary = "当前会话未关联"
        elif status == "referenced_not_found":
            summary = "聊天有引用，但业务库未找到"
        elif status == "filtered":
            summary = "引用不属于当前客户，已过滤"
        else:
            summary = "关联信息存在冲突，请人工核对"
        return AssistanceFactOut(label=label, status=status, summary=summary)

    @staticmethod
    def _summary(intent: str, context: dict[str, Any], acknowledged: bool) -> str:
        verified = sum(
            context[key]["status"] == "present" for key in ("order", "product", "work_order")
        )
        stage = "客服已经说明白了，客户也确认了" if acknowledged else "这件事还要继续跟进"
        return f"{intent}。{stage}。订单、商品和售后信息已核对 {verified} 项。"

    @staticmethod
    def _service_handling(context: dict[str, Any]) -> str:
        work_order = context["work_order"].get("record") or {}
        handling_by_type = {
            "replacement_exchange": "客服已经登记补发或换货，接下来按工单继续跟进。",
            "offline_payment": "客服已经确认退款条件，并提交了线下打款。",
            "logistics": "客服已经查过订单和物流，正在跟进快递进度。",
            "adverse_reaction": "客服先让客户停用产品，也登记了不适情况，接下来由人工跟进。",
            "after_sale_return": "客服已经说明怎么寄回，也建了售后工单跟进退货和退款。",
        }
        if work_order.get("ticket_type") in handling_by_type:
            return handling_by_type[work_order["ticket_type"]]
        if work_order:
            return "客服已经查过相关记录，接下来按售后工单继续跟进。"
        return "客服还在确认客户要解决什么，目前没有关联的售后记录。"

    @staticmethod
    def _current_status(context: dict[str, Any], acknowledged: bool) -> str:
        work_order = context["work_order"].get("record") or {}
        ticket_type = work_order.get("ticket_type")
        if acknowledged and ticket_type == "after_sale_return":
            return "客户已经确认怎么寄回。现在等退件物流更新，之后再处理退款。"
        if acknowledged:
            return "客户已经清楚怎么处理了。现在等后续结果。"
        status = {"pending": "待处理", "processing": "处理中", "completed": "已完成"}.get(
            work_order.get("status"), "待进一步核实"
        )
        return f"售后工单现在是{status}。客服还要继续跟进。"

    @staticmethod
    def _next_actions(intent: str, context: dict[str, Any], acknowledged: bool) -> list[str]:
        work_order = context["work_order"].get("record") or {}
        if acknowledged:
            actions = ["礼貌收尾，不要重复追问客户已经说明的问题"]
            if work_order:
                status = {"pending": "待处理", "processing": "处理中", "completed": "已完成"}.get(
                    work_order.get("status"), work_order.get("status") or "待确认"
                )
                work_order_id = work_order.get("external_id", "已关联工单")
                actions.append(
                    f"确认售后工单 {work_order_id} 保持“{status}”状态，并与已告知客户的进度一致"
                )
            return actions[:3]

        actions = ["根据完整聊天中尚未解决的诉求继续处理"]
        if context["order"]["status"] != "present":
            actions.append("请客户提供订单号，再核对订单归属")
        if "售后" in intent and context["work_order"]["status"] != "present":
            actions.append("确认诉求后创建并关联售后工单")
        elif context["work_order"]["status"] == "present":
            actions.append("按已关联工单状态说明当前处理进度")
        if "肌肤不适" in intent:
            actions.append("建议停止继续试用并由人工按安全流程跟进，严重时及时就医")
        return actions[:3]

    @staticmethod
    def _suggested_reply(
        issue_message: str,
        intent: str,
        context: dict[str, Any],
        acknowledged: bool,
    ) -> str:
        opening = "我已经看过您刚才的描述，也核对了当前会话里的相关记录。"
        work_order = context["work_order"].get("record") or {}
        if acknowledged:
            resolution = work_order.get("resolution") or work_order.get("description")
            detail = f"，关于{resolution}的处理进度请按刚才说明留意" if resolution else ""
            return (
                f"不客气，很高兴能帮到您{detail}。后续如果状态有变化或还有其他问题，随时联系我们。"
            )
        if "肌肤不适" in intent:
            return (
                f"{opening}肌肤不适需要优先处理，请先暂停使用相关产品。"
                "为了继续协助您，请补充出现不适的时间、部位和目前情况；"
                "如症状明显或持续，请及时就医。"
            )
        order = context["order"].get("record")
        if "物流" in intent and order:
            status = order.get("status") or "待确认"
            logistics = order.get("logistics_no")
            detail = f"当前订单状态为“{status}”"
            if logistics:
                detail += f"，物流单号为 {logistics}"
            return f"{opening}{detail}。我会继续按这笔订单为您核实，如有新的进度会及时说明。"
        if not issue_message:
            return "您好，请告诉我这次希望查询或处理的问题，我会结合订单和售后记录为您核实。"
        return (
            f"{opening}我理解您这次主要需要处理{intent}。"
            "我会先确认相关记录和可处理范围，再给您明确答复。"
        )
