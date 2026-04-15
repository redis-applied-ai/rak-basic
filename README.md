# RAK Minimal Release Demo

This directory is shaped like the companion repo for the Redis Agent Kit `0.1.0` launch.

It is intentionally small:

- one app file
- one optional MCP file
- a tiny browser UI
- real worker-based execution with Redis

The goal is to show how little code it takes to get RAK's opinionated tasking flow into a project.

The code is heavily commented so a reader can map the implementation back to the
core release stories:

- Redis as the control plane for agents
- clean human-in-the-loop pause and resume
- streaming and observability as first-class primitives
- bring your own agent framework
- one agent, multiple protocols
- built-in pipeline endpoints for the RAG story

## Internal benchmark

For the release blog, keep the scale comparison as an internal artifact rather
than a product feature. This directory includes `benchmark_scale.py`, which
compares:

- `inline`: simulated work done directly in the request path
- `queued`: the same number of tasks accepted quickly and handed to workers

That keeps the public demo clean while still giving us a figure for the blog
that illustrates the architectural value of worker-backed execution.

## What it demonstrates

- durable background task execution
- live progress and token streaming over SSE
- human approval with `request_input()` and `submit_input()`
- REST, A2A, and ACP exposure from the same app
- a shape that can double as a release smoke test

## Quickstart

```bash
docker run -d -p 6379:6379 redis:8
uv sync
```

Start the API:

```bash
uv run uvicorn app:app --reload
```

Start the worker in a second terminal:

```bash
cd examples/minimal_release_demo
uv run rak worker --name minimal_release_demo --tasks app:tasks
```

Open the demo:

```bash
open http://localhost:8000/demo
```

## Endpoints

- UI: `GET /demo`
- Task create: `POST /chat`
- Task state: `GET /tasks/{task_id}`
- Task stream: `GET /tasks/{task_id}/stream`
- Task input: `POST /tasks/{task_id}/input`
- A2A discovery: `GET /.well-known/agent.json`
- ACP discovery: `GET /agents`
- OpenAPI docs: `GET /docs`
