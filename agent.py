from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Awaitable, Callable, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

load_dotenv(Path(__file__).with_name(".env"))

EmitCallback = Callable[[str], Awaitable[None]]
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MODEL_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0"))


def _approval_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"confirm": {"type": "boolean"}},
        "required": ["confirm"],
    }


def _requires_human_approval(message: str) -> bool:
    lowered = message.lower()
    destructive = any(
        term in lowered
        for term in (
            "delete",
            "drop",
            "truncate",
            "wipe",
            "remove",
            "purge",
            "clear",
            "invalidate",
        )
    )
    sensitive_target = any(
        term in lowered
        for term in (
            "database",
            "db",
            "table",
            "tables",
            "row",
            "rows",
            "record",
            "records",
            "cache",
            "redis",
            "key",
            "keys",
            "production",
            "prod",
        )
    )
    return destructive and sensitive_target


class AgentState(TypedDict):
    message: str
    context: str
    response: str


async def _emit_optional(callback: EmitCallback | None, payload: str) -> None:
    if callback is not None and payload:
        await callback(payload)


def _chunk_to_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return str(content) if content else ""


def _build_messages(state: AgentState) -> list[dict[str, str]]:
    context = state["context"].strip()
    system_lines = [
        "You are a concise, helpful assistant in a Redis Agent Kit demo.",
        "Answer in 2-4 short paragraphs or bullets.",
        "If extra context is supplied, use it. If it is empty, answer from general knowledge.",
        "When relevant, explain concepts clearly for engineers evaluating agent infrastructure.",
    ]
    if context:
        system_lines.extend(["", "Additional context:", context])
    return [
        {"role": "system", "content": "\n".join(system_lines)},
        {"role": "user", "content": state["message"]},
    ]


def _create_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=MODEL_NAME,
        temperature=MODEL_TEMPERATURE,
        streaming=True,
    )


def _build_graph(
    *,
    emit_update: EmitCallback | None = None,
    emit_token: EmitCallback | None = None,
):
    llm = _create_llm()

    async def generate(state: AgentState) -> AgentState:
        await _emit_optional(emit_update, "Running LangGraph model node...")
        messages = _build_messages(state)
        chunks: list[str] = []
        async for chunk in llm.astream(messages):
            text = _chunk_to_text(chunk)
            if text:
                chunks.append(text)
                await _emit_optional(emit_token, text)

        response = "".join(chunks).strip()
        if not response:
            final = await llm.ainvoke(messages)
            response = str(getattr(final, "content", "")).strip()

        return {
            "message": state["message"],
            "context": state["context"],
            "response": response,
        }

    graph = StateGraph(AgentState)
    graph.add_node("generate", generate)
    graph.set_entry_point("generate")
    graph.add_edge("generate", END)
    return graph.compile()


async def run_langgraph_agent(
    message: str,
    *,
    rag_context: str = "",
    emit_update: EmitCallback | None = None,
    emit_token: EmitCallback | None = None,
) -> dict[str, Any]:
    graph = _build_graph(emit_update=emit_update, emit_token=emit_token)
    result = await graph.ainvoke(
        {
            "message": message,
            "context": rag_context,
            "response": "",
        }
    )
    return {"response": result["response"]}


async def run_task(ctx) -> dict[str, Any]:
    await ctx.emitter.emit("Worker picked up the task.")

    task = await ctx.kit.task_manager.get_task(ctx.task_id)
    input_response = getattr(task, "input_response", None) if task else None

    if _requires_human_approval(ctx.message):
        if input_response and input_response.get("confirm") is not None:
            if not bool(input_response.get("confirm")):
                await ctx.emitter.emit("Human approval declined. Task cancelled.")
                return {
                    "response": "Cancelled. Database-destructive actions require explicit human approval."
                }
            await ctx.emitter.emit("Human approval received. Continuing task.")
        else:
            await ctx.emitter.emit(
                "This request needs human approval before it can continue."
            )
            await ctx.kit.task_manager.request_input(
                task_id=ctx.task_id,
                prompt="This request asks to perform a destructive action on production data or cache. Approve before the agent continues?",
                json_schema=_approval_schema(),
                metadata={"kind": "approval", "reason": "destructive_operation"},
            )
            return {"response": "Awaiting human approval."}

    return await run_langgraph_agent(
        ctx.message,
        rag_context=getattr(ctx, "rag_context", ""),
        emit_update=ctx.emitter.emit,
        emit_token=ctx.emitter.emit_token,
    )
