"""Round-2 model bake-off: multi-turn scenarios against the real agent.

    uv run python -m canvas_copilot.evals.bakeoff
    uv run python -m canvas_copilot.evals.bakeoff --model qwen2.5:3b --runs 2
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx
from langchain_core.messages import AIMessage

from canvas_copilot.evals.harness import build_eval_agent, run_scenario
from canvas_copilot.evals.scenarios import (
    Scenario,
    load_scenarios,
    score_turn,
    universal_checks,
)

DEFAULT_MODELS = ["qwen2.5:3b", "qwen2.5:7b"]
DEFAULT_RUNS = 2
_OLLAMA = "http://localhost:11434"


def _ollama_models() -> dict[str, int]:
    resp = httpx.get(f"{_OLLAMA}/api/tags", timeout=5)
    resp.raise_for_status()
    return {m["name"]: m.get("size", 0) for m in resp.json().get("models", [])}


def _preflight(models: list[str]) -> dict[str, int]:
    try:
        available = _ollama_models()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Cannot reach Ollama at {_OLLAMA} ({exc}). Start `ollama serve`.")
    missing = [m for m in models if m not in available]
    if missing:
        raise SystemExit(
            "Models not pulled:\n  "
            + "\n  ".join(f"ollama pull {m}" for m in missing)
        )
    return available


def _run_model(model_name: str, scenarios: list[Scenario], runs: int) -> dict:
    scenario_scores: dict[str, list[float]] = {s.id: [] for s in scenarios}
    latencies: list[float] = []
    check_totals = {"tool": [0, 0], "answer": [0, 0], "refusal": [0, 0], "other": [0, 0]}
    failures: list[str] = []

    for run in range(runs):
        agent = build_eval_agent(model_name=model_name, ollama_host=_OLLAMA)
        for scenario in scenarios:
            start = time.perf_counter()
            try:
                transcripts = run_scenario(agent, scenario)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{scenario.id} run {run}: {type(exc).__name__}: {exc}")
                scenario_scores[scenario.id].append(0.0)
                continue
            latencies.append(time.perf_counter() - start)

            turn_fracs: list[float] = []
            for tr in transcripts:
                checks = score_turn(tr.turn, tr.messages)
                answer = next(
                    (m.content for m in reversed(tr.messages)
                     if isinstance(m, AIMessage) and m.content),
                    "",
                )
                checks += universal_checks(answer)
                for c in checks:
                    bucket = (
                        "refusal" if "refused" in c.label
                        else "tool" if "tool" in c.label.lower() or "called" in c.label
                        else "answer" if "answer" in c.label
                        else "other"
                    )
                    check_totals[bucket][1] += 1
                    if c.passed:
                        check_totals[bucket][0] += 1
                    else:
                        failures.append(f"{scenario.id}/run{run}: {c.label} — {c.detail}")
                passed = sum(c.passed for c in checks)
                turn_fracs.append(passed / len(checks))
            scenario_scores[scenario.id].append(statistics.mean(turn_fracs))

    def rate(pair: list[int]) -> float | None:
        return round(pair[0] / pair[1], 3) if pair[1] else None

    per_scenario = {sid: round(statistics.mean(v), 3) for sid, v in scenario_scores.items()}
    return {
        "overall": round(statistics.mean(per_scenario.values()), 3),
        "tool_checks": rate(check_totals["tool"]),
        "answer_checks": rate(check_totals["answer"]),
        "refusal_checks": rate(check_totals["refusal"]),
        "latency_p50_s": round(statistics.median(latencies), 1) if latencies else None,
        "latency_p95_s": (
            round(sorted(latencies)[min(len(latencies) - 1, int(len(latencies) * 0.95))], 1)
            if latencies else None
        ),
        "per_scenario": per_scenario,
        "sample_failures": failures[:40],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m canvas_copilot.evals.bakeoff")
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--scenarios", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=Path("evals/reports"))
    args = parser.parse_args(argv)

    models = args.models or DEFAULT_MODELS
    sizes = _preflight(models)
    scenarios = load_scenarios(args.scenarios)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runs": args.runs,
        "scenarios": [s.id for s in scenarios],
        "models": {},
    }
    for name in models:
        print(f"\n=== {name} ({sizes.get(name, 0) / 1e9:.1f} GB) ===")
        summary = _run_model(name, scenarios, args.runs)
        summary["size_gb"] = round(sizes.get(name, 0) / 1e9, 2)
        report["models"][name] = summary
        print(f"  overall {summary['overall']}  tools {summary['tool_checks']}  "
              f"answers {summary['answer_checks']}  refusal {summary['refusal_checks']}  "
              f"p50 {summary['latency_p50_s']}s")

    print(f"\n{'model':16}{'overall':>9}{'tools':>8}{'answers':>9}{'refusal':>9}"
          f"{'p50 s':>8}{'GB':>7}")
    for name, s in report["models"].items():
        print(f"{name:16}{s['overall']!s:>9}{s['tool_checks']!s:>8}"
              f"{s['answer_checks']!s:>9}{s['refusal_checks']!s:>9}"
              f"{s['latency_p50_s']!s:>8}{s['size_gb']!s:>7}")

    args.report_dir.mkdir(parents=True, exist_ok=True)
    path = args.report_dir / f"bakeoff2_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"\nreport written: {path}")


if __name__ == "__main__":
    main()
