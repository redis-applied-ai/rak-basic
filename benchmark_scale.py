from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from uuid import uuid4

from app import _kit

INLINE_WORK_SECONDS = 0.45


async def _simulate_inline_work(message: str, index: int) -> dict[str, int]:
    """Stand-in for work that would otherwise block the request path."""
    await asyncio.sleep(INLINE_WORK_SECONDS)
    return {"item": index + 1, "message_length": len(message)}


async def run_trial(count: int, message: str) -> dict[str, float]:
    """Measure inline request-path time vs queued acceptance time."""
    inline_started = time.perf_counter()
    for index in range(count):
        await _simulate_inline_work(message, index)
    inline_elapsed_ms = (time.perf_counter() - inline_started) * 1000

    batch_id = uuid4().hex[:8]
    queued_started = time.perf_counter()
    for index in range(count):
        await _kit.create_and_submit_task(
            message=f"{message} [benchmark {batch_id} item {index + 1}]",
            session_id=f"benchmark-{batch_id}-{index + 1}",
        )
    queued_elapsed_ms = (time.perf_counter() - queued_started) * 1000

    return {
        "inline_request_path_ms": inline_elapsed_ms,
        "queued_accept_ms": queued_elapsed_ms,
        "speedup_ratio": inline_elapsed_ms / max(queued_elapsed_ms, 1),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Internal benchmark for the RAK minimal release demo."
    )
    parser.add_argument("--count", type=int, default=8, help="Tasks per trial.")
    parser.add_argument("--runs", type=int, default=5, help="Number of benchmark trials.")
    parser.add_argument(
        "--message",
        default="Summarize why background workers help agent reliability.",
        help="Prompt used for the queued side of the benchmark.",
    )
    args = parser.parse_args()

    count = max(1, min(args.count, 100))
    runs = max(1, min(args.runs, 20))

    results = []
    for run_index in range(runs):
        result = await run_trial(count=count, message=args.message)
        results.append(result)
        print(
            f"run {run_index + 1}: "
            f"inline={result['inline_request_path_ms']:.1f} ms, "
            f"queued_accept={result['queued_accept_ms']:.1f} ms, "
            f"ratio={result['speedup_ratio']:.2f}x"
        )

    inline_median = statistics.median(r["inline_request_path_ms"] for r in results)
    queued_median = statistics.median(r["queued_accept_ms"] for r in results)
    ratio_median = statistics.median(r["speedup_ratio"] for r in results)

    print("\nSummary")
    print(f"- tasks per trial: {count}")
    print(f"- runs: {runs}")
    print(f"- median inline request-path time: {inline_median:.1f} ms")
    print(f"- median queued acceptance time: {queued_median:.1f} ms")
    print(f"- median request-path ratio: {ratio_median:.2f}x")
    print(
        "- note: this compares time spent in the request path, not end-to-end completion time."
    )


if __name__ == "__main__":
    asyncio.run(main())
