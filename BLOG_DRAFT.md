# Introducing the Redis Agent Kit 0.1.0

One of our core philosophies on the Applied AI team at Redis is that we try to
"eat our own dogfood." We want to build tools that we ourselves would actually
choose to use when building systems.

That has been true for our work with `redisvl`, where we have spent the last few
years building vector-search-driven applications and steadily refining the
abstractions we reach for in real projects. It is also the mindset that led us
to Redis Agent Kit.

Last year we started building and deploying more agent applications of our own.
The goal was not to sit in a room and imagine the perfect abstraction. The goal
was to ship agents, put them in front of people, and learn which parts were
common enough that we should not have to keep rebuilding them.

What we found was that all our agents needed to be able to:
- distribute load across workers to scale
- push updates out to users in a reliable way
- start, resume, and get input on long-running tasks
- be quickly available in a variety of protocols (REST, A2A, ACP, etc.)
- handle data versioning and pipeline sync for knowledge bases

The goal of RAK is to give you a tested, opinionated way of solving these problems
regardless of how you built your agent.

## Distributing load and async tasking

Most folks interested in RAK, probably have already created logic for their agent
and want a quick way to scale it without thinking about how to setup all the streams
and consumer groups in order to do so.

Let’s assume you already have a LangGraph agent that looks something like
this:

Note: This doesn't have to be a LangGraph agent. RAK is designed to be agnostic
in this regard.

```python
from langgraph.graph import START, END, StateGraph

class DemoState(dict):
    pass


async def call_model(state: DemoState) -> DemoState:
    return {"response": f"LangGraph handled: {state['message']}"}


graph = StateGraph(DemoState)
graph.add_node("call_model", call_model)
graph.add_edge(START, "call_model")
graph.add_edge("call_model", END)
langgraph_agent = graph.compile()
```

Then wrap your agent as an async callable and pass to the agent kit:

```python
from redis_agent_kit import (
    AgentKit,
    ChannelScope,
    EmitterMiddleware,
    StreamConfig,
    TaskContext,
)

async def demo_agent(ctx: TaskContext) -> dict[str, str]:
    # This is your code. RAK handles tasking, workers, and streaming around it.
    result = await langgraph_agent.ainvoke({"message": ctx.message})
    return {"response": result["response"]}

STREAM_CONFIG = StreamConfig(enabled=True, channels={ChannelScope.TASK})

kit = AgentKit(
    redis_url="redis://localhost:6379",
    agent_callable=demo_agent,
    middleware=[EmitterMiddleware(start_message="Task queued. Waiting for a worker...")],
    queue_name="minimal_release_demo",
    stream_config=STREAM_CONFIG,
)
```

With that small bit of code around your existing agent, you get a lot of the system
behavior teams usually end up wiring by hand:

- durable task creation and status tracking, so work has a lifecycle you can actually inspect
- persisted results and failures, so execution leaves behind something useful operationally
- worker-backed execution outside the request path, so your API can hand work off instead of waiting on it
- built-in streaming, so progress updates and token output can be observed while the task is still running
- clean pause-and-resume semantics, so human input can fit into the same task lifecycle instead of becoming a separate special case

## Extending to Multiple Protocols

A practical service often needs to do more than answer a web request.

The same agent might need to be called by an application backend, discovered by
another agent runtime, or exposed to MCP-aware tooling. We did not want the
multi-protocol story to require a totally separate setup.

Once the tasking model exists, exposing the same service in more AI-native ways
becomes much less work. That is part of the appeal here too: you are not
building one-off protocol adapters around bespoke execution code.

In the demo, the same app exposes REST, A2A, and ACP, with an optional MCP file
next to it:

```python
app = create_app(
    redis_url=REDIS_URL,
    kit=kit,
    stream_config=STREAM_CONFIG,
    enable_a2a=True,
    enable_acp=True,
    agent_card=agent_card,
    agent_manifest=agent_manifest,
)
```

That gives us:

- REST endpoints for the browser UI
- A2A discovery and invocation
- ACP discovery and runs
- optional MCP exposure from a second tiny file

Again, the theme is consistency. One tasking layer, one service, several ways to
meet the outside world.

## Middleware and Pipeline add ons

The demo keeps the public story focused, but RAK goes further than the small
sample app shows. There is more middleware for common cross-cutting concerns,
and the package also ships built-in pipeline APIs for document preparation and
ingestion.

If you want more than tasking, streaming, and human approval, the repo already
has deeper examples and the pieces to keep building:

- middleware for emitters, results, threads, and RAG context
- pipeline APIs for prepare, ingest, and full document workflows
- examples showing OpenAI, LangGraph, RAG, tools, and memory-backed flows
