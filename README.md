# RAK demo

This repo is a minimal Redis Agent Kit example.

It shows:

- background task execution with workers
- live progress and token streaming over SSE
- a real LangGraph agent behind the task interface
- REST, A2A, and ACP exposure from one app

The main point is that this does not require much code. The API entry point stays small in
[app.py](app.py), and the actual agent implementation lives in
[langgraph_agent.py](langgraph_agent.py).

## File breakdown

- [app.py](app.py) - API entry point, AgentKit wiring, and HTTP routes
- [langgraph_agent.py](langgraph_agent.py) - LangGraph graph definition and agent execution logic
- `index.html` - small browser UI for the demo
- `benchmark_scale.py` - runs concurrent inline vs queued benchmarks against the same agent and writes CSV output
- `plot_benchmark_results.py` - turns benchmark CSVs into PNG charts with pandas/matplotlib
- `artifacts/benchmark_sample/` - sample benchmark CSVs and charts checked into the repo

## Quickstart

```bash
uv sync
```

Create a `.env` file with your API key before you start the server or worker:

```bash
OPENAI_API_KEY=your-key-here
```

```bash
docker run -d -p 6379:6379 redis:8
```

Start the API:

```bash
uv run uvicorn app:app --reload
```

Start the worker in a second terminal:

```bash
uv run rak worker --name minimal_release_demo --tasks app:tasks
```

Open the demo:

```bash
open http://localhost:8000/demo
```

## Quick concurrency benchmark

Start Redis, the API, and the worker as shown above, then run:

```bash
uv run python benchmark_scale.py --users 2 4 8
```

That creates a timestamped directory under `artifacts/benchmark/` with:

- `requests.csv` - one row per simulated user request
- `summary.csv` - one row per scenario (`inline` or `queued`)

The benchmark compares:

- `inline` - work is done in the request path
- `queued` - work is accepted quickly and completed by workers

It uses the same LangGraph/OpenAI-backed agent in both modes, so start with small
concurrency values unless you explicitly want a larger external-model load test.

To turn those CSVs into graphs:

```bash
uv sync --extra benchmark
uv run python plot_benchmark_results.py artifacts/benchmark/<timestamp>
```

To reproduce the sample figures checked into this repo:

```bash
uv run python benchmark_scale.py --users 2 4 8 --output-dir artifacts/benchmark_sample
uv run python plot_benchmark_results.py artifacts/benchmark_sample
```

## Sample benchmark figures

These benchmark artifacts are illustrative. Since the demo now runs a live LangGraph
agent, current benchmark numbers depend on model latency, provider rate limits, and
the machine running the worker.

The takeaway is simple:

- inline requests hold the caller open for the full workload
- queued requests return quickly and let workers absorb the load
- completion latency still grows with concurrency, but API responsiveness stays much better

![Throughput](artifacts/benchmark_sample/throughput_rps.png)

![Completion latency boxplot](artifacts/benchmark_sample/completion_latency_boxplot.png)

## Endpoints

- UI: `GET /demo`
- Task create: `POST /chat`
- Inline direct run: `POST /chat-inline`
- Task state: `GET /tasks/{task_id}`
- Task stream: `GET /tasks/{task_id}/stream`
- Task input: `POST /tasks/{task_id}/input`
- A2A discovery: `GET /.well-known/agent.json`
- ACP discovery: `GET /agents`
- OpenAPI docs: `GET /docs`
