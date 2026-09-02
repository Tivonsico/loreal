from __future__ import annotations

import json
import re
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field


class OpenAICompatibleProviderError(RuntimeError):
    pass


class ModelAdvice(BaseModel):
    # Only the allowlisted fields below leave the provider boundary. Harmless
    # extra keys should not discard an otherwise usable model answer.
    model_config = ConfigDict(extra="ignore")

    intent: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=220)
    service_handling: str = Field(min_length=1, max_length=180)
    current_status: str = Field(min_length=1, max_length=140)
    urgency: Literal["normal", "medium", "high"]
    risks: list[str] = Field(max_length=5)
    next_actions: list[str] = Field(min_length=1, max_length=5)
    suggested_reply: str = Field(min_length=1, max_length=2000)
    evidence_message_ids: list[int] = Field(max_length=5)
    emotion: Literal["positive", "neutral", "anxious", "angry", "sad"] = "neutral"
    emotion_confidence: float = Field(default=0.5, ge=0, le=1)
    customer_tags: list[str] = Field(default_factory=list, max_length=4)
    trail_summaries: list[str] = Field(default_factory=list, max_length=4)


class EmotionBatchAdvice(BaseModel):
    """Narrow, allowlisted result used by the all-conversation risk scan."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str = Field(min_length=1, max_length=100)
    emotion: Literal["positive", "neutral", "anxious", "angry", "sad"]
    confidence: float = Field(ge=0, le=1)
    risk_type: Literal[
        "none", "emotion_escalation", "repeat_contact", "repeat_refund", "complaint"
    ] = "none"
    severity: Literal["low", "medium", "high"] = "low"
    summary: str = Field(min_length=1, max_length=120)
    evidence_message_ids: list[int] = Field(default_factory=list, max_length=5)


class OpenAICompatibleChatProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        json_mode: bool = True,
        reasoning_mode: str = "auto",
    ):
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._is_bigmodel = urlparse(self._endpoint).hostname == "open.bigmodel.cn"
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._json_mode = json_mode
        self._reasoning_mode = reasoning_mode

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, context: dict[str, Any]) -> ModelAdvice:
        system_prompt = (
            "你是美妆电商客服的接待辅助。按时间顺序阅读完整聊天和关联业务事实，不能只看最后一句。"
            "先在内部提取七类信息，不要输出中间步骤：客户遇到的问题、问题原因、客户想要的结果、"
            "客服关键操作、当前进度、下一步待办，以及金额/时效/物流/安全风险等关键数据。"
            "只依据输入事实，不得编造。业务 section 不是 present 时，不得当作已核验事实。"
            "reply_handbook 为 present 时必须遵循；资料不可用时仍要独立判断，不能把缺少话术当风险。"
            "信息按重要性取舍：保留会改变处理结果的原因、方案、金额、时效和状态；忽略纯问候、"
            "称呼、道谢、致歉、祝福和重复确认。带有业务事实的句子即使同时致谢，也必须保留事实。"
            "字段严格分工：intent 只写整段聊天的核心问题和客户目标，绝不能写‘无新诉求’；"
            "service_handling 写客服做过的关键业务动作；current_status 写事情办到哪一步、还等什么；"
            "summary 用 2 至 3 句串起问题、解决办法和结果。四个字段都不得复制聊天原句。"
            "写给忙碌客服看，不是写报告。用完整主谓句和日常口语，多用‘已经、但是、没法、"
            "希望、现在等’，少用‘寻求、处于、经核实、流程闭环’。不要写成动作标签或电报体。"
            "表达尽量简短。每句话只表达一个重点。复杂内容拆成短句。"
            "少用多层转折、因果、并列和长定语。不能漏掉关键事实。"
            "intent 不超过40字；summary 不超过120字；service_handling 不超过100字；"
            "current_status 不超过70字。关键原因、金额和时效允许在不同字段适度重复。"
            "接下来有三组用户事实与标准 JSON 示例。学习示例的字段分工、信息取舍和说话方式，"
            "不得照抄示例事实。涉及肌肤不适时不得诊断；严重时建议及时就医。"
            "next_actions 必须具体且不能重复已完成动作。suggested_reply 必须给出可发送的回复，"
            "即使无需追问也不能留空。"
            "输出一个 JSON 对象，只能包含 intent、summary、service_handling、current_status、"
            "urgency、risks、next_actions、"
            "suggested_reply、evidence_message_ids、emotion、emotion_confidence、"
            "customer_tags、trail_summaries。"
            "urgency 只能是 normal、medium 或 high。evidence_message_ids 只能引用输入消息 ID。"
            "emotion 只能是 positive、neutral、anxious、angry、sad；"
            "customer_tags 是最多4个简短消费或服务偏好标签；trail_summaries 最多4条。"
        )
        few_shot_messages = self._few_shot_messages()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                *few_shot_messages,
                {
                    "role": "user",
                    "content": "请分析以下客服事实包并返回 JSON：\n"
                    + json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "stream": False,
        }
        if self._json_mode:
            payload["response_format"] = {"type": "json_object"}
        self._apply_assistance_reasoning(payload)
        body = self._send_payload(payload, optional_reasoning_fallback=self._is_bigmodel)
        try:
            completion = json.loads(body)
            content = completion["choices"][0]["message"]["content"]
            advice = self._parse_advice(content)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OpenAICompatibleProviderError("在线模型返回内容未通过结构化校验") from exc

        messages = context["chat"]["messages"]
        valid_message_ids = {item["id"] for item in messages}
        evidence = [
            message_id
            for message_id in advice.evidence_message_ids
            if message_id in valid_message_ids
        ]
        if not evidence:
            evidence = [item["id"] for item in messages if item["sender_role"] == "customer"][-3:]
        return advice.model_copy(update={"evidence_message_ids": evidence})

    def classify_emotions(self, contexts: list[dict[str, Any]]) -> list[EmotionBatchAdvice]:
        """Classify a bounded batch without generating replies or exposing business records."""
        if not contexts:
            return []
        if len(contexts) > 50:
            raise ValueError("单批情绪分析不得超过 50 个会话")

        safe_inputs = [self._safe_emotion_input(item) for item in contexts]
        expected_ids = {item["conversation_id"] for item in safe_inputs}
        prompt = (
            "你是客服会话情绪分类器。只依据给定聊天，不得编造、诊断或生成客服回复。"
            "每个 conversation_id 必须恰好返回一条。emotion 只能是 positive、neutral、"
            "anxious、angry、sad；risk_type 只能是 none、emotion_escalation、"
            "repeat_contact、repeat_refund、complaint；severity 只能是 low、medium、high。"
            "confidence 为 0 到 1。summary 不超过 60 字。evidence_message_ids 只能引用输入 ID。"
            "返回 JSON 对象，唯一顶层字段为 items。"
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"conversations": safe_inputs},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            "stream": False,
        }
        if self._json_mode:
            payload["response_format"] = {"type": "json_object"}
        self._apply_classification_reasoning(payload)
        body = self._send_payload(payload, optional_reasoning_fallback=True)
        try:
            completion = json.loads(body)
            content = completion["choices"][0]["message"]["content"]
            parsed = self._parse_json_object(content)
            raw_items = parsed["items"]
            if not isinstance(raw_items, list):
                raise ValueError("items 不是数组")
            results = [EmotionBatchAdvice.model_validate(item) for item in raw_items]
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OpenAICompatibleProviderError("在线情绪分类返回内容未通过结构化校验") from exc

        returned_ids = [item.conversation_id for item in results]
        if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != expected_ids:
            raise OpenAICompatibleProviderError("在线情绪分类返回的会话 ID 不完整")
        valid_evidence = {
            item["conversation_id"]: {message["id"] for message in item["messages"]}
            for item in safe_inputs
        }
        return [
            item.model_copy(
                update={
                    "evidence_message_ids": [
                        message_id
                        for message_id in item.evidence_message_ids
                        if message_id in valid_evidence[item.conversation_id]
                    ]
                }
            )
            for item in results
        ]

    def _apply_classification_reasoning(self, payload: dict[str, Any]) -> None:
        mode = self._reasoning_mode
        if self._is_bigmodel:
            if mode in {"auto", "disabled"}:
                payload["thinking"] = {"type": "disabled"}
            else:
                payload["thinking"] = {"type": "enabled"}
                payload["reasoning_effort"] = mode
            payload["max_tokens"] = 1800
        elif mode in {"minimal", "low"}:
            payload["reasoning_effort"] = mode

    def _apply_assistance_reasoning(self, payload: dict[str, Any]) -> None:
        """Apply only endpoint capabilities known for the configured provider."""
        if not self._is_bigmodel:
            return
        mode = self._reasoning_mode
        if mode == "disabled":
            payload["thinking"] = {"type": "disabled"}
        else:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "low" if mode == "auto" else mode
        payload["max_tokens"] = 1200

    @staticmethod
    def _safe_emotion_input(context: dict[str, Any]) -> dict[str, Any]:
        conversation_id = context.get("conversation_id") or (context.get("conversation") or {}).get(
            "id"
        )
        messages = context.get("messages") or (context.get("chat") or {}).get("messages") or []
        if not conversation_id:
            raise ValueError("情绪分析输入缺少 conversation_id")
        safe_messages = []
        for message in messages:
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            safe_messages.append(
                {
                    "id": int(message["id"]),
                    "sender_role": message.get("sender_role"),
                    "content": content[:2000],
                }
            )
        return {"conversation_id": str(conversation_id), "messages": safe_messages[-30:]}

    def _send_payload(
        self, payload: dict[str, Any], *, optional_reasoning_fallback: bool
    ) -> bytes:
        try:
            return self._request_payload(payload)
        except HTTPError as exc:
            details = self._http_error_details(exc)
            if (
                optional_reasoning_fallback
                and exc.code in {400, 422}
                and self._unsupported_optional_parameter(details)
                and any(key in payload for key in ("thinking", "reasoning_effort", "max_tokens"))
            ):
                fallback = dict(payload)
                for key in ("thinking", "reasoning_effort", "max_tokens"):
                    fallback.pop(key, None)
                try:
                    return self._request_payload(fallback)
                except HTTPError as retry_exc:
                    raise OpenAICompatibleProviderError(
                        f"在线模型接口返回 HTTP {retry_exc.code}"
                    ) from retry_exc
            raise OpenAICompatibleProviderError(f"在线模型接口返回 HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise OpenAICompatibleProviderError("在线模型接口连接失败") from exc

    def _request_payload(self, payload: dict[str, Any]) -> bytes:
        request = Request(
            self._endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            return response.read(2 * 1024 * 1024)

    @staticmethod
    def _http_error_details(error: HTTPError) -> str:
        try:
            return error.read(64 * 1024).decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - broken third-party error streams
            return ""

    @staticmethod
    def _unsupported_optional_parameter(details: str) -> bool:
        lowered = details.lower()
        parameter = any(
            name in lowered for name in ("thinking", "reasoning_effort", "max_tokens")
        )
        unsupported = any(
            marker in lowered
            for marker in ("unknown", "unsupported", "unrecognized", "extra inputs", "不支持")
        )
        return parameter and unsupported

    @staticmethod
    def _parse_json_object(content: Any) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ValueError("模型内容不是文本")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].rstrip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("模型内容不含 JSON 对象")
        parsed = json.loads(cleaned[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("模型 JSON 不是对象")
        return parsed

    @staticmethod
    def _few_shot_messages() -> list[dict[str, str]]:
        examples = (
            (
                "示例事实：客户的退货已经被仓库签收，但售后期已经过了，系统没法原路退款。"
                "客服决定线下退10元，客户提供了收款信息，申请已经提交，预计1-3个工作日到账。",
                {
                    "intent": (
                        "客户把货退回去了，但是售后期已经过了，没法退款，希望能线下把钱退回来"
                    ),
                    "summary": (
                        "仓库已经收到退货了，但是系统没法原路退款。"
                        "客服改成线下退10元，申请已经提交了。"
                    ),
                    "service_handling": (
                        "客服确认退货已经入库了，拿到收款信息后提交了10元退款申请。"
                    ),
                    "current_status": "退款申请已经提交了，现在等财务审核，预计1-3个工作日到账。",
                    "urgency": "medium",
                    "risks": [],
                    "next_actions": ["留意退款到账情况，超时后跟进财务"],
                    "suggested_reply": "退款申请已经提交了，请留意到账通知。",
                    "evidence_message_ids": [1, 2],
                },
            ),
            (
                "示例事实：客户的包裹三天没有更新，想知道什么时候能收到。客服查到快递卡在中转站，"
                "已经联系快递催件，承诺第二天继续查看。",
                {
                    "intent": "客户的包裹几天没动，想知道什么时候能收到",
                    "summary": "包裹卡在中转站了。客服已经联系快递催件，明天还会继续查看。",
                    "service_handling": "客服查了物流轨迹，也联系快递催件了。",
                    "current_status": "现在等快递更新物流，明天还没动就继续跟进。",
                    "urgency": "medium",
                    "risks": [],
                    "next_actions": ["明天检查物流轨迹是否更新"],
                    "suggested_reply": "已经帮您催快递了，我明天再帮您看一次物流进度。",
                    "evidence_message_ids": [1, 2],
                },
            ),
            (
                "示例事实：客户用了喷雾后脸上紧绷刺痛，想申请退货。客服让客户先停用，"
                "已经通过退货申请，仓库收到退件后退款。",
                {
                    "intent": "客户用了喷雾后脸上不舒服，想退货退款",
                    "summary": "客户用了喷雾后脸上紧绷刺痛。客服先让客户停用，也通过了退货申请。",
                    "service_handling": "客服让客户先停用喷雾，并帮客户通过了退货申请。",
                    "current_status": "现在等客户寄回，仓库收到后再退款。",
                    "urgency": "high",
                    "risks": ["如果不适持续或加重，需要及时就医"],
                    "next_actions": ["确认客户已经停用产品", "跟进退件物流"],
                    "suggested_reply": "请先停用这款喷雾。如果不适持续或加重，请及时就医。",
                    "evidence_message_ids": [1, 2],
                },
            ),
        )
        messages: list[dict[str, str]] = []
        for fact, answer in examples:
            messages.append({"role": "user", "content": fact})
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(answer, ensure_ascii=False, separators=(",", ":")),
                }
            )
        return messages

    @staticmethod
    def _parse_advice(content: Any) -> ModelAdvice:
        data = OpenAICompatibleChatProvider._parse_json_object(content)

        urgency_map = {
            "一般": "normal",
            "普通": "normal",
            "低": "normal",
            "中": "medium",
            "中等": "medium",
            "高": "high",
            "紧急": "high",
        }
        data["urgency"] = urgency_map.get(data.get("urgency"), data.get("urgency"))
        for field in ("risks", "next_actions"):
            if isinstance(data.get(field), str):
                data[field] = [data[field]]
            if isinstance(data.get(field), list):
                data[field] = data[field][:5]
        for field in ("customer_tags", "trail_summaries"):
            if isinstance(data.get(field), str):
                data[field] = [data[field]]
            if isinstance(data.get(field), list):
                data[field] = [
                    str(item).strip()[:80]
                    for item in data[field][:4]
                    if str(item).strip()
                ]
        if isinstance(data.get("evidence_message_ids"), list):
            data["evidence_message_ids"] = [
                int(item)
                for item in data["evidence_message_ids"][:5]
                if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
            ]
        for field, limit in (
            ("intent", 80),
            ("summary", 220),
            ("service_handling", 180),
            ("current_status", 140),
            ("suggested_reply", 2000),
        ):
            if isinstance(data.get(field), str):
                data[field] = OpenAICompatibleChatProvider._fit_text(data[field], limit)
        if not data.get("suggested_reply"):
            data["suggested_reply"] = (
                "好的，当前处理进度已经为您记录。后续如果状态有变化或还有其他问题，随时联系我们。"
            )
        data["intent"] = OpenAICompatibleChatProvider._remove_low_signal_clauses(
            data["intent"], remove_service_actions=True, sentence_style=False
        )
        for field in ("summary", "service_handling", "current_status"):
            data[field] = OpenAICompatibleChatProvider._remove_low_signal_clauses(
                data[field], sentence_style=True
            )
        return ModelAdvice.model_validate(data)

    @staticmethod
    def _fit_text(value: str, limit: int) -> str:
        text = value.strip()
        if len(text) <= limit:
            return text
        clipped = text[:limit]
        boundary = max(clipped.rfind(mark) for mark in ("。", "！", "？", ";", "；"))
        if boundary >= limit // 2:
            return clipped[: boundary + 1]
        return clipped.rstrip("，、；; ") + "。"

    @staticmethod
    def _remove_low_signal_clauses(
        value: str,
        *,
        remove_service_actions: bool = False,
        sentence_style: bool = True,
    ) -> str:
        low_signal = (
            "谢谢",
            "感谢",
            "致谢",
            "不客气",
            "生活愉快",
            "欢迎再次",
            "随时咨询",
            "理解与支持",
        )
        sentences = [
            sentence.strip() for sentence in re.split(r"[。！？；;]+", value) if sentence.strip()
        ]
        substantive = (
            "退款",
            "退货",
            "金额",
            "到账",
            "审核",
            "申请",
            "物流",
            "快递",
            "工单",
            "入库",
            "售后",
            "打款",
            "停用",
            "寄回",
        )
        kept_sentences = []
        for sentence in sentences:
            clauses = [clause.strip() for clause in sentence.split("，") if clause.strip()]
            kept_clauses = []
            for clause in clauses:
                has_courtesy = any(term in clause for term in low_signal)
                has_business_fact = any(term in clause for term in substantive) or any(
                    char.isdigit() for char in clause
                )
                if has_courtesy and not has_business_fact:
                    continue
                if remove_service_actions and clause.startswith("客服"):
                    continue
                kept_clauses.append(clause)
            if kept_clauses:
                kept_sentences.append("，".join(kept_clauses))
        if not kept_sentences:
            return value.strip()
        if not sentence_style:
            return "，".join(kept_sentences)
        return "。".join(kept_sentences) + "。"
