import base64
import json
import os
from functools import lru_cache
from typing import Any

import boto3

from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent

from input_guard import blocked_reply, text_events, user_text
from mcp_client.client import get_papers_gw_mcp_client
from model.load import load_model

app = BedrockAgentCoreApp()
log = app.logger

SYSTEM_PROMPT = """
You are a research paper assistant working with the user's personal library of arXiv papers.

Tools:
- search_arxiv: find NEW papers on arXiv by topic, to suggest or add to the library. Never use it to answer
  a question about the content of papers the user has already saved.
- add_paper: save a paper to the user's library (needs an arXiv ID). A newly saved paper takes a few
  seconds to index and cannot be searched until list_papers shows its status as READY.
- list_papers: show the user's saved papers and their status.
- search_library: find passages in the user's saved papers. Use it for any question about what the
  user's papers say.

Answering questions about the user's papers:
- If the user names a specific paper, model or author (for example "what does BERT use?"), call
  list_papers FIRST and check that a saved paper's title matches. If none does, say that paper is not in
  their library and stop: do not search for it, and do not use another paper's passages as a substitute.
- Otherwise call search_library. To focus on particular papers, use the arXiv IDs from list_papers as
  arxiv_ids.
- Write the search_library query as a complete question or sentence that includes the paper or topic
  (for example "What learning rate schedule and warmup steps does the Transformer use?"), not as bare
  keywords like "warmup steps": short keyword queries match poorly and can return nothing.
- Questions about what a saved paper says, including numbers, results and methods, always go to
  search_library, never to search_arxiv.
- Base the answer only on the passages returned, and cite each claim as (paper title, p. N) using the
  paper_title and page fields.
- If search_library returns no passages, say you could not find it in the user's saved papers. Do not
  answer from your own knowledge.
- Check each passage's paper_title against the paper, model or author the user asked about. If the
  passages come from a different paper than the one the user named, say that the named paper is not in
  their library; do not present those passages as being about the paper they asked about.
- Only use arXiv IDs returned by a tool or given by the user; never invent papers, passages or IDs.

Saving changes the user's library, so be careful with it. If the user does not give an arXiv ID,
or refers to earlier results you cannot see (for example "the second one"), do not search and
guess: ask which paper they mean. Never choose a paper on the user's behalf.
"""


def strip_trailing_tool_use(messages: Any) -> list[dict]:
    """Strip toolUse blocks from the tail until the last message has none."""
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")

    messages = list(messages)
    while messages:
        last = messages[-1]
        if not isinstance(last, dict):
            raise ValueError("each message must be an object")
        original_content = last.get("content", [])
        if not isinstance(original_content, list) or not all(isinstance(block, dict) for block in original_content):
            raise ValueError("each message content value must be a list of content blocks")

        content = [block for block in original_content if "toolUse" not in block]
        if len(content) == len(original_content):
            break
        if content:
            messages[-1] = {**last, "content": content}
            break
        messages.pop()

    return messages


def _extract_prompt(payload: dict):
    """Accept validated harness messages or a plain prompt string."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if "messages" in payload:
        return strip_trailing_tool_use(payload["messages"])
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    return prompt


def _caller_authorization(context) -> str:
    """The caller's own Authorization header (forwarded because it is on the runtime allowlist)."""
    headers = getattr(context, "request_headers", None) or {}
    authorization = headers.get("Authorization")
    if not authorization:
        raise PermissionError("no Authorization header on the request")
    return authorization


def _user_id(authorization: str) -> str:
    """The caller's `sub` claim. Runtime has already validated the JWT, so only the payload is read."""
    payload = authorization.split(" ", 1)[-1].split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


def _memory_id() -> str:
    """The id of the memory the CLI created for this agent. Its variable name is MEMORY_<NAME>_ID,
    where the name comes from the agent, so look for the one that exists instead of hard-coding it."""
    ids = [v for k, v in os.environ.items() if k.startswith("MEMORY_") and k.endswith("_ID")]
    if len(ids) != 1:
        raise RuntimeError(f"expected exactly one MEMORY_*_ID variable, found {len(ids)}")
    return ids[0]


def _session_manager(authorization: str, context) -> AgentCoreMemorySessionManager | None:
    """Short-term memory keyed by user (actor) and conversation (session)."""
    if os.environ.get("MEMORY_DISABLED") == "1":  # local experiments only; never set on the Runtime
        return None
    if not context.session_id:
        raise ValueError("no session id on the request")
    return AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(
            memory_id=_memory_id(),
            session_id=context.session_id,
            actor_id=_user_id(authorization),
        ),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )


@lru_cache(maxsize=1)
def _guardrail_client():
    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent.....")
    prompt = _extract_prompt(payload)
    authorization = _caller_authorization(context)
    # Guardrails -> Get tools from GW -> Send info (query, sys prompt, tools)to the model for deciding

    # Input guardrail: screen what the user typed before anything else runs. A blocked request gets
    # the guardrail's fixed reply, with no tool discovery, no model call and no memory write.
    guardrail_id = os.environ.get("GUARDRAIL_ID")
    if guardrail_id:
        reply = blocked_reply(_guardrail_client(), guardrail_id,
                              os.environ.get("GUARDRAIL_VERSION", "DRAFT"), user_text(prompt))
        if reply:
            log.info("Request blocked by the input guardrail")
            for event in text_events(reply):
                yield event
            return

    # Built per request: the gateway client and the memory keys carry *this* caller's identity.
    gateway = get_papers_gw_mcp_client(authorization)
    with gateway:
        agent = Agent(
            model=load_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=gateway.list_tools_sync(),
            session_manager=_session_manager(authorization, context),
        )

        async for event in agent.stream_async(prompt):
            if not isinstance(event, dict) or "event" not in event:
                continue
            cbs = event["event"].get("contentBlockStart")
            if cbs is not None and not cbs.get("start"):
                continue
            yield event


if __name__ == "__main__":
    app.run()
