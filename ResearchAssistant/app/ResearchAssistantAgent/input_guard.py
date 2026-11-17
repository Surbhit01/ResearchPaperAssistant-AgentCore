import logging

from botocore.exceptions import BotoCoreError, ClientError

log = logging.getLogger(__name__)

DEFAULT_BLOCKED_REPLY = "I can only help with finding, saving and discussing research papers."
UNAVAILABLE_REPLY = "I couldn't run the safety check just now. Please try again in a moment."


def user_text(prompt):
    """What the user typed: a plain prompt, or the last user message of a message list."""
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        for message in reversed(prompt):
            if isinstance(message, dict) and message.get("role") == "user":
                return " ".join(b["text"] for b in message.get("content", []) if isinstance(b, dict) and "text" in b)
    return ""


def blocked_reply(client, guardrail_id, version, text):
    """None when the text may go on to the agent; otherwise the fixed reply to give the user instead.

    Fails closed: if the guardrail cannot be checked, the request is not passed to the model.
    """
    if not text.strip():
        return None
    try:
        result = client.apply_guardrail(guardrailIdentifier=guardrail_id, guardrailVersion=version,
                                        source="INPUT", content=[{"text": {"text": text}}])
    except (ClientError, BotoCoreError):
        log.exception("input guardrail check failed")
        return UNAVAILABLE_REPLY
    if result.get("action") != "GUARDRAIL_INTERVENED": #GUARDRAIL_INTERVENED -> Guardrail will block the request. #None Nothing found worth blocking
        return None
    outputs = result.get("outputs") or []
    return (outputs[0].get("text") if outputs else None) or DEFAULT_BLOCKED_REPLY


def text_events(text):
    """The reply as the same stream events the agent emits, so callers handle it like any answer."""
    yield {"event": {"messageStart": {"role": "assistant"}}}
    yield {"event": {"contentBlockDelta": {"delta": {"text": text}, "contentBlockIndex": 0}}}
    yield {"event": {"contentBlockStop": {"contentBlockIndex": 0}}}
    yield {"event": {"messageStop": {"stopReason": "end_turn"}}}
