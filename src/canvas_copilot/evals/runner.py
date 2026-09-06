"""Model bake-off: single-turn tool selection.

For each case we send the query + tool list to a model and check its FIRST tool
call. Each case runs several times (local small models are not fully
deterministic) and we report the pass rate, latency, and model size.

    uv run python -m canvas_copilot.evals                 # both 3B candidates
    uv run python -m canvas_copilot.evals --model qwen2.5:3b --runs 5
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from canvas_copilot.evals.cases import Case, load_cases
from canvas_copilot.evals.tools import ALL_TOOLS

DEFAULT_MODELS = ["qwen2.5:3b", "llama3.2:3b"]
DEFAULT_RUNS = 3

_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not _OLLAMA_HOST.startswith("http"):
    _OLLAMA_HOST = f"http://{_OLLAMA_HOST}"

# Minimal prompt for the bake-off only. The real system prompt is designed with
# the user in M4/M6 and will live in prompts/.
SYSTEM_PROMPT = (
    "You are Canvas Copilot, a read-only assistant that helps a student find "
    "logistics about their Canvas courses: assignments, due dates, and exams. "
    "Use the provided tools to look things up. When the student refers to one "
    "specific course by name, nickname, or abbreviation, call resolve_course "
    "first. Never help complete, solve, write, or explain the solution to "
    "graded work; if asked, refuse briefly and call no tool. Today is {today}."
)


@dataclass
class CaseResult:
    case_id: str
    is_refusal: bool
    passes: int
    runs: int
    latencies: list[float] = field(default_factory=list)
    sample_call: str = ""


def _ollama_models() -> dict[str, int]:
    """Map of locally available model tag -> size in bytes."""
    resp = httpx.get(f"{_OLLAMA_HOST}/api/tags", timeout=5)
    resp.raise_for_status()
    return {m["name"]: m.get("size", 0) for m in resp.json().get("models", [])}


def _preflight(models: list[str]) -> dict[str, int]:
    try:
        available = _ollama_models()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Cannot reach Ollama at {_OLLAMA_HOST} ({exc}).\n"
            "Start it with `ollama serve` or `brew services start ollama`."
        )
    missing = [m for m in models if m not in available]
    if missing:
        pulls = "  ".join(f"ollama pull {m}" for m in missing)
        raise SystemExit(f"Models not pulled: {missing}\n  {pulls}")
    return available


def _build_model(name: str):
    from langchain_ollama import ChatOllama

    llm = ChatOllama(
        model=name,
        temperature=0.0,
        num_predict=512,
        base_url=_OLLAMA_HOST,
    )
    return llm.bind_tools(ALL_TOOLS)


def _describe(calls: list[dict]) -> str:
    if not calls:
        return "<no tool call>"
    first = calls[0]
    return f"{first['name']}({first.get('args', {})})"


def _case_passes(case: Case, calls: list[dict]) -> bool:
    if case.expect_refusal:
        return len(calls) == 0
    if not calls or calls[0]["name"] not in case.accept_tools:
        return False
    arg_blob = " ".join(str(v) for v in (calls[0].get("args") or {}).values()).lower()
    return all(needle.lower() in arg_blob for needle in case.arg_contains.values())


def _run_case(bound_model, case: Case, runs: int, today: str) -> CaseResult:
    system = SystemMessage(content=SYSTEM_PROMPT.format(today=today))
    result = CaseResult(case.id, case.expect_refusal, passes=0, runs=runs)
    for _ in range(runs):
        start = time.perf_counter()
        try:
            msg = bound_model.invoke([system, HumanMessage(content=case.query)])
            calls = list(getattr(msg, "tool_calls", []) or [])
        except Exception as exc:  # noqa: BLE001 - keep the sweep going
            result.latencies.append(time.perf_counter() - start)
            result.sample_call = result.sample_call or f"<error: {type(exc).__name__}>"
            continue
        result.latencies.append(time.perf_counter() - start)
        result.sample_call = result.sample_call or _describe(calls)
        if _case_passes(case, calls):
            result.passes += 1
    return result


def _summarize(results: list[CaseResult], size_bytes: int) -> dict:
    latencies = sorted(lat for r in results for lat in r.latencies)
    tool = [r for r in results if not r.is_refusal]
    refusal = [r for r in results if r.is_refusal]

    def rate(rs: list[CaseResult]) -> float | None:
        runs = sum(r.runs for r in rs)
        return round(sum(r.passes for r in rs) / runs, 3) if runs else None

    return {
        "tool_accuracy": rate(tool),
        "refusal_accuracy": rate(refusal),
        "latency_p50_s": round(statistics.median(latencies), 2) if latencies else None,
        "latency_p95_s": (
            round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 2)
            if latencies
            else None
        ),
        "size_gb": round(size_bytes / 1e9, 2) if size_bytes else None,
        "per_case": {r.case_id: f"{r.passes}/{r.runs}" for r in results},
    }


def _fmt(value: object) -> str:
    return "-" if value is None else str(value)


def _print_table(report: dict) -> None:
    print("\n" + "=" * 74)
    header = f"{'model':18}{'tool_acc':>10}{'refusal':>10}{'p50 s':>8}{'p95 s':>8}{'size GB':>10}"
    print(header)
    print("-" * 74)
    for name, s in report["models"].items():
        print(
            f"{name:18}{_fmt(s['tool_accuracy']):>10}{_fmt(s['refusal_accuracy']):>10}"
            f"{_fmt(s['latency_p50_s']):>8}{_fmt(s['latency_p95_s']):>8}"
            f"{_fmt(s['size_gb']):>10}"
        )


def _write_report(report: dict, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"bakeoff_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m canvas_copilot.evals")
    parser.add_argument(
        "--model", action="append", dest="models",
        help="model tag (repeatable); default: both 3B candidates",
    )
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=Path("evals/reports"))
    args = parser.parse_args(argv)

    models = args.models or DEFAULT_MODELS
    sizes = _preflight(models)
    cases = load_cases(args.cases)
    today = date.today().isoformat()

    report: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runs_per_case": args.runs,
        "cases": [c.id for c in cases],
        "models": {},
    }

    for name in models:
        print(f"\n=== {name} ===")
        bound = _build_model(name)
        results: list[CaseResult] = []
        for case in cases:
            r = _run_case(bound, case, args.runs, today)
            results.append(r)
            mark = "ok" if r.passes == r.runs else ("~" if r.passes else "XX")
            print(f"  {mark:>3}  {case.id:28}{r.passes}/{r.runs}  {r.sample_call[:56]}")
        report["models"][name] = _summarize(results, sizes.get(name, 0))

    _print_table(report)
    path = _write_report(report, args.report_dir)
    print(f"\nreport written: {path}")
