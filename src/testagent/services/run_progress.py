"""Execution receipt counts shared by run details, history and task summaries."""

COUNT_KEYS = ("passed", "failed", "error", "blocked", "skipped")


def run_counts(executions: list[dict], total: int | None) -> dict:
    counts = {k: 0 for k in COUNT_KEYS}
    for execution in executions:
        if execution["status"] in counts:
            counts[execution["status"]] += 1
    done = sum(counts.values())
    return {"total": total if total is not None else done, "done": done, **counts}
