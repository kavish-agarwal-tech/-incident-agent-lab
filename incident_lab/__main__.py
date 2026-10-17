"""Run with python -m incident_lab from the repository root."""

import argparse
import json
from pathlib import Path

from .evaluation import run_features, run_retrieval
from .fixtures import seed
from .runtime import Denied, Runtime
from .store import Store
from .workflow import demo, execution_session


def write_json(path, value):
    # Reports are standalone artifacts; create the output directory on first use.
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    # CLI entry point: parse an experiment, select fixture actors, then call the
    # trusted host APIs. Actual agent tools remain behind Runtime.call.
    parser = argparse.ArgumentParser(description="Incident Agent Learning Lab (simulation only)")
    commands = parser.add_subparsers(dest="command", required=True)
    demo_parser = commands.add_parser("demo", help="Investigate; optionally simulate approval and execution")
    demo_parser.add_argument("--db", default="artifacts/demo.db")
    demo_parser.add_argument("--execute", action="store_true", help="Simulate Bob's approval and Carol's execution")
    demo_parser.add_argument("--workflow", default="INC-101")
    for command in ("approve", "execute", "trace"):
        # Separate commands demonstrate durable state across fresh Python processes.
        child = commands.add_parser(command)
        child.add_argument("--db", default="artifacts/demo.db")
        if command != "trace":
            child.add_argument("--proposal", default="INC-101:rollback")
            child.add_argument("--user", default="bob" if command == "approve" else "carol")
    evaluate = commands.add_parser("eval", help="Run isolated feature evals and chunking benchmarks")
    evaluate.add_argument("--output", default="artifacts/eval-report.json")
    args = parser.parse_args()
    if args.command == "eval":
        # Acceptance cases are pass/fail gates; retrieval scores are descriptive
        # comparisons. Keep both in one report without treating them as equivalent.
        report = {"features": run_features(), "retrieval": run_retrieval()}
        write_json(args.output, report)
        features = report["features"]
        print(f"Feature evals: {features['passed']}/{features['total']} passed")
        for result in features["results"]:
            if not result["passed"]:
                print(f"FAIL {result['id']}: expected={result['expected']} actual={result['actual']}")
        print("Retrieval benchmark: 6 strategies x 4 questions (descriptive metrics)")
        for strategy in dict.fromkeys(r["strategy"] for r in report["retrieval"]["results"]):
            rows = [r for r in report["retrieval"]["results"] if r["strategy"] == strategy]
            coverage = sum(r["required_phrase_coverage"] for r in rows) / len(rows)
            print(f"  {strategy}: mean required-phrase coverage={coverage:.2f}")
        print(f"Report: {args.output}")
        # A nonzero exit code lets a future CI job fail on a feature regression.
        return 0 if features["passed"] == features["total"] else 1
    store = Store(args.db)
    try:
        # Reopen existing business state without resetting approvals or executions.
        # Sessions are process-local and are created afresh for the requested action.
        seed(store)
        runtime = Runtime(store)
        if args.command == "demo":
            result = demo(store, args.execute, args.workflow)
        elif args.command == "approve":
            # This simulates a human UI action, not an agent-callable approval tool.
            result = runtime.approve(args.user, args.proposal)
        elif args.command == "execute":
            proposal = store.get("proposal", args.proposal)
            # --user selects a fixture actor; it is not production authentication.
            # The new task uses that actor's rights while retaining the proposal's originator.
            handle = runtime.session(args.user, "remediator", proposal["incident"], proposal["scope"],
                                     {"rollback.execute"}, originator=proposal["proposed_by"])
            result = runtime.call(handle, "rollback.execute", {"proposal_id": args.proposal})
        else:
            # trace is an operator-facing view of the trusted local store.
            result = store.events()
        print(json.dumps(result, indent=2))
        if args.command == "demo":
            print(f"Durable state: {args.db}; inspect with: python -m incident_lab trace --db {args.db}")
        return 0
    except (Denied, KeyError, ValueError) as exc:
        print(f"Denied or invalid state: {exc}")
        return 1
    finally:
        # Release the SQLite connection even when a denial returns exit code 1.
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
