from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import redis.asyncio as redis_lib

from redis_agent_kit import (
    AgentCard,
    AgentKit,
    AgentManifest,
    ChannelScope,
    EmitterMiddleware,
    Skill,
    StreamConfig,
    side_effect,
)
from redis_agent_kit.api import create_app

# -----------------------------------------------------------------------------
# Demo setup: keep the top-level config tiny so readers can see the RAK shape.
# This is the "Redis as the control plane" story in miniature: one Redis URL,
# one queue, one AgentKit, and the rest of the task lifecycle is handled by RAK.
# -----------------------------------------------------------------------------
REDIS_URL = os.getenv("RAK_REDIS_URL") or os.getenv("REDIS_URL") or "redis://localhost:6379"
QUEUE_NAME = "minimal_release_demo"
STREAM_CONFIG = StreamConfig(enabled=True, channels={ChannelScope.TASK})
SIDE_EFFECT_REDIS = redis_lib.from_url(REDIS_URL, decode_responses=True)
DEMO_HTML = Path(__file__).with_name("index.html").read_text()


# -----------------------------------------------------------------------------
# Human-in-the-loop story: this expensive-ish analysis is intentionally wrapped
# in @side_effect so a resumed task does not redo the work from scratch.
# RAK stores the completion marker and cached result in Redis between runs.
# -----------------------------------------------------------------------------
@side_effect(store_result=True, redis_client=SIDE_EFFECT_REDIS)
async def classify_request(message: str) -> str:
    await asyncio.sleep(0.4)
    lowered = message.lower()
    risky_terms = ("delete", "drop", "destroy", "wipe", "production", "prod")
    if any(term in lowered for term in risky_terms):
        return "approval_required"
    return "safe"


def _approval_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "confirm": {"type": "boolean"},
        },
        "required": ["confirm"],
    }


def _token_chunks(text: str) -> list[str]:
    return re.findall(r"\S+\s*|\n", text)


def _build_reply(message: str, approval_state: str) -> str:
    lines = [
        "This demo keeps the agent code intentionally small while still exercising RAK's core tasking model.",
        "",
        f"Your prompt: {message}",
        "",
        "What just happened:",
        "- The API accepted work quickly and queued it in Redis.",
        "- A worker picked the task up outside the request path.",
        "- Progress updates streamed live over SSE.",
    ]

    if approval_state == "approved":
        lines.append("- The task paused for human approval, then resumed on the same task id.")
    elif approval_state == "declined":
        lines.append("- The task paused for human approval and was safely cancelled.")
    else:
        lines.append("- No human approval was needed for this request.")

    lines.extend(
        [
            "",
            "This directory is meant to be the release companion repo shape:",
            "- tiny UV setup",
            "- tiny UI",
            "- real worker-based execution",
            "- optional A2A, ACP, and MCP endpoints",
        ]
    )
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Bring-your-own-agent-framework story: the handler is just an async function.
# You could replace this with OpenAI, LangGraph, tools, memory, or your own
# stack and keep the same tasking, streaming, and protocol shell around it.
# -----------------------------------------------------------------------------
async def demo_agent(ctx) -> dict[str, Any]:
    await ctx.emitter.emit("Worker picked up the task.")

    task = await ctx.kit.task_manager.get_task(ctx.task_id)
    input_response = task.input_response if task else None

    if input_response is not None:
        confirmed = bool(input_response.get("confirm"))
        await ctx.kit.task_manager.clear_input(ctx.task_id)
        if not confirmed:
            return {"response": _build_reply(ctx.message, "declined")}
        await ctx.emitter.emit("Approval received. Resuming work.")
        approval_state = "approved"
    else:
        approval_state = "not_needed"
        await ctx.emitter.emit("Classifying the request.")
        request_class = await classify_request(ctx.message)
        if request_class == "approval_required":
            await ctx.emitter.emit("This request needs a human decision.")
            await ctx.kit.task_manager.request_input(
                task_id=ctx.task_id,
                prompt="This demo treats destructive or production-flavored prompts as gated. Continue?",
                json_schema=_approval_schema(),
                metadata={"kind": "approval"},
            )
            return {"response": "Awaiting approval."}

    await ctx.emitter.emit("Preparing response.")
    reply = _build_reply(ctx.message, approval_state)

    # -------------------------------------------------------------------------
    # Streaming story: milestone updates are emitted with emit(), while tokens
    # stream separately with emit_token() so the UI gets live output without
    # persisting every token to task history.
    # -------------------------------------------------------------------------
    for chunk in _token_chunks(reply):
        await asyncio.sleep(0.03)
        await ctx.emitter.emit_token(chunk)

    return {"response": reply}


# -----------------------------------------------------------------------------
# Opinionated RAK configuration in a few lines:
# - AgentKit wires Redis, task state, workers, and middleware together
# - EmitterMiddleware gives us visible task progress with almost no boilerplate
# - StreamConfig turns on SSE-ready event publishing for the UI
# -----------------------------------------------------------------------------
def _create_kit() -> AgentKit:
    return AgentKit(
        redis_url=REDIS_URL,
        agent_callable=demo_agent,
        middleware=[EmitterMiddleware(start_message="Task queued. Waiting for a worker...")],
        queue_name=QUEUE_NAME,
        stream_config=STREAM_CONFIG,
    )


_kit = _create_kit()
tasks = [_kit.worker_task]

agent_card = AgentCard(
    name="RAK Minimal Demo",
    description="A tiny Redis Agent Kit demo app with background tasks and streaming.",
    url="http://localhost:8000",
    skills=[Skill(id="demo", name="Demo", description="Show tasking and approval flows")],
)

agent_manifest = AgentManifest(
    name="rak-minimal-demo",
    description="A tiny Redis Agent Kit demo app with background tasks and streaming.",
)

# -----------------------------------------------------------------------------
# Multi-protocol story: one app exposes REST plus A2A and ACP discovery. The
# optional mcp_server.py file in this directory covers the MCP side of the same
# release narrative. create_app() also mounts the built-in /pipelines routes,
# which is the hook for the RAG ingestion story even though this UI stays lean.
# -----------------------------------------------------------------------------
app = create_app(
    redis_url=REDIS_URL,
    kit=_kit,
    stream_config=STREAM_CONFIG,
    enable_a2a=True,
    enable_acp=True,
    agent_card=agent_card,
    agent_manifest=agent_manifest,
    title="RAK Minimal Release Demo",
    description="Small companion app for the Redis Agent Kit 0.1.0 release.",
)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
async def demo_ui() -> HTMLResponse:
    return HTMLResponse(DEMO_HTML)


@app.post("/chat")
async def chat(request: Request, body: ChatRequest) -> dict[str, Any]:
    return await _kit.create_and_submit_task(
        message=body.message,
        session_id=body.session_id,
    )
