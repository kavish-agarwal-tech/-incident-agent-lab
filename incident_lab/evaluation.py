"""Versioned, scenario-based acceptance evals; no LLM-as-judge needed."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

from .chunking import STRATEGIES, chunk_document, event_chunks, retrieve
from .context import Context
from .fixtures import SCOPE, seed
from .runtime import Denied, Runtime
from .store import Store
from .workflow import demo, execution_session, investigate

ROOT = Path(__file__).resolve().parent.parent


def expect(condition, explanation):
    if not condition:
        raise AssertionError(explanation)


def scenario(name, store, runtime):
    """Each branch performs a user-visible integration experiment, not a policy mock."""
    if name == "cli_process_flow":
        path = store.db.execute("PRAGMA database_list").fetchone()[2]

        def command(*arguments, expected_code=0):
            process = subprocess.run(
                [sys.executable, "-m", "incident_lab", *arguments, "--db", path],
                cwd=ROOT, text=True, capture_output=True, timeout=15,
            )
            expect(process.returncode == expected_code,
                   f"CLI {arguments} returned {process.returncode}: {process.stdout} {process.stderr}")
            return process.stdout

        output = command("demo")
        expect("awaiting_human_approval" in output, "CLI demo did not stop at proposal")
        expect("approval_required" in command("execute", expected_code=1), "Missing approval allowed")
        expect("approver_permission" in command("approve", "--user", "carol", expected_code=1),
               "Operator incorrectly approved")
        command("approve", "--user", "bob")
        expect("user_permission" in command("execute", "--user", "alice", expected_code=1),
               "Approval upgraded Alice")
        first = json.loads(command("execute", "--user", "carol"))
        second = json.loads(command("execute", "--user", "carol"))
        trace = json.loads(command("trace"))
        expect(not first["replayed"] and second["replayed"], "CLI retry repeated execution")
        expect(sum(e["event"] == "execution.completed" for e in trace) == 1,
               "CLI flow produced duplicate side effects")
        return {"separate_processes": 8, "executions": 1, "replays": 1}
    if name == "happy_path":
        result = demo(store, execute=True)
        execution = result["execution"]
        expect((execution["originator"], execution["approved_by"], execution["executed_by"])
               == ("alice", "bob", "carol"), "Human identities must remain separate")
        expect(store.get("deployment", "checkout")["version"] == "v41", "Rollback missing")
        expect(store.get("finding", "INC-101")["verification"].startswith("pending"),
               "Do not claim unobserved recovery")
        return {"execution": execution}
    if name == "proposal_only":
        result = demo(store)
        expect(not store.all("approval") and not store.all("execution"), "Unexpected side effect")
        expect(store.get("deployment", "checkout")["version"] == "v42", "Deployment changed")
        return {"status": result["status"]}
    if name in {"bounded_handoff", "delegation_escalation"}:
        parent = runtime.session("alice", "coordinator", "INC-101", SCOPE, {"docs.read"})
        child, envelope = runtime.delegate(parent, "researcher", "task-1", "Find prerequisites",
                                           {"docs.read"}, ["runbook-checkout"])
        if name == "delegation_escalation":
            runtime.delegate(parent, "remediator", "task-2", "Escalate", {"rollback.execute"})
        expect(runtime.sessions[child].user == "alice", "Initiator changed on delegation")
        expect(set(envelope) >= {"objective", "evidence_refs", "budget", "completion_criteria"},
               "Incomplete task contract")
        expect(not {"roles", "credentials", "transcript", "session_handle"} & set(envelope),
               "Handoff leaked authority or entire transcript")
        return {"envelope": envelope}
    if name == "context_isolation":
        a, b = Context(store, "a", "logs"), Context(store, "b", "runbooks")
        a.fact("private working note", "logs-101")
        expect(not b.state["facts"] and not b.recent, "Specialist context leaked")
        return {"isolated": True}
    if name == "checkpoint_resume":
        investigate(runtime)
        checkpoint = store.get("checkpoint", "INC-101:logs")
        path = store.db.execute("PRAGMA database_list").fetchone()[2]
        reopened = Store(path)
        try:
            restored = Context.resume(reopened, "INC-101:logs")
            expect(restored.state == checkpoint["state"], "Checkpoint lost state")
            expect(restored.state["facts"] and restored.state["open_questions"]
                   and restored.state["rejected"] and restored.state["constraints"],
                   "Critical state missing")
            expect(not restored.recent, "Raw noise survived compaction")
            event = next(e for e in reopened.events() if e["event"] == "context.compacted")
            expect(event["after_units"] < event["before_units"], "No context reduction")
            return {"before_units": event["before_units"], "after_units": event["after_units"]}
        finally:
            reopened.close()
    if name == "pinned_overflow":
        context = Context(store, "tiny", "too much pinned state", budget=10)
        context.fact("critical fact " * 30, "logs-101")
        try:
            context.compact()
        except ValueError:
            expect(context.state["facts"], "Pinned facts were discarded")
            return {"overflow_visible": True}
        raise AssertionError("Compaction silently accepted oversized pinned state")
    if name == "viewer_execute":
        # A read-only viewer can get a remediator session; that does not grant execute.
        handle = runtime.session("victor", "remediator", "INC-101", SCOPE, {"docs.read"})
        runtime.call(handle, "rollback.execute", {"proposal_id": "does-not-exist"})
    if name in {"investigator_execute", "task_grant"}:
        agent = "investigator" if name == "investigator_execute" else "remediator"
        handle = runtime.session("carol", agent, "INC-101", SCOPE, {"docs.read"})
        runtime.call(handle, "rollback.execute", {"proposal_id": "does-not-exist"})
    if name in {"tenant_read", "denial_audit"}:
        handle = runtime.session("alice", "investigator", "INC-101", SCOPE, {"logs.read"})
        try:
            runtime.call(handle, "logs.read", {"evidence_id": "tenant-b-logs"})
        except Denied:
            if name == "tenant_read":
                raise
            expect(store.events()[-1]["reason"] == "resource_scope", "Denial not audited")
            expect(not store.all("execution"), "Denied read changed deployment")
            return {"event": store.events()[-1]}
    if name == "production_session":
        runtime.session("carol", "remediator", "INC-101", {**SCOPE, "environment": "production"},
                        {"rollback.execute"})
    if name == "user_revoked":
        handle = runtime.session("carol", "remediator", "INC-101", SCOPE, {"rollback.execute"})
        runtime.users["carol"]["role"] = "viewer"
        runtime.call(handle, "rollback.execute", {"proposal_id": "x"})
    if name == "grant_mint_ceiling":
        runtime.session("victor", "remediator", "INC-101", SCOPE, {"rollback.execute"})
    if name in {"tool_discovery", "hidden_tool", "identity_spoof", "resource_type", "tool_budget"}:
        grant = {"docs.read", "logs.read"} if name == "hidden_tool" else {"docs.read"}
        handle = runtime.session("alice", "researcher", "INC-101", SCOPE, grant)
        if name == "tool_discovery":
            tools = runtime.list_tools(handle)
            expect([tool["name"] for tool in tools] == ["docs.read"], "Tool exposure too broad")
            return {"tools": tools}
        if name == "hidden_tool":
            runtime.call(handle, "logs.read", {"evidence_id": "logs-101"})
        if name == "identity_spoof":
            runtime.call(handle, "docs.read", {"evidence_id": "runbook-checkout", "user": "carol"})
        if name == "resource_type":
            runtime.call(handle, "docs.read", {"evidence_id": "logs-101"})
        if name == "tool_budget":
            for _ in range(9):
                runtime.call(handle, "docs.read", {"evidence_id": "runbook-checkout"})
    if name == "unknown_session":
        runtime.call("caller-invented", "docs.read", {"evidence_id": "runbook-checkout"})
    if name == "injection":
        investigate(runtime)
        logs = store.get("evidence", "logs-101")
        expect(any("export secrets" in r["text"] for r in logs["records"]), "Attack absent")
        expect(not store.all("approval") and not store.all("execution"), "Evidence gained authority")
        expect(all(e.get("action") != "export.secrets" for e in store.events()), "Attack executed")
        return {"malicious_text_present": True, "side_effects": 0,
                "limitation": "Scripted agents; this is not an LLM jailbreak evaluation"}
    if name in {"chunk_provenance", "overlap", "recursive_bound", "prerequisites",
                "parent_expansion", "event_grouping"}:
        return chunk_scenario(name, store)

    # Shared setup for approval/execution scenarios.
    proposal = investigate(runtime)
    key = proposal["action_id"]
    handle = execution_session(runtime, proposal)
    if name == "wrong_approver":
        runtime.approve("carol", key)
    if name == "checkpoint_no_authority":
        checkpoint = store.get("checkpoint", "INC-101:logs")
        checkpoint["state"]["approved"] = True
        store.put("checkpoint", "INC-101:logs", checkpoint)
        Context.resume(store, "INC-101:logs")
    if name in {"approval_missing", "checkpoint_no_authority"}:
        runtime.call(handle, "rollback.execute", {"proposal_id": key})
    if name == "proposal_conflict":
        other = runtime.session("carol", "remediator", "INC-101", SCOPE, {"rollback.propose"})
        runtime.call(other, "rollback.propose", {k: proposal[k] for k in
                     ("action_id", "incident", "from_version", "to_version")})
    runtime.approve("bob", key)
    if name == "approval_no_upgrade":
        alice = runtime.session("alice", "remediator", "INC-101", SCOPE, {"rollback.propose"})
        runtime.call(alice, "rollback.execute", {"proposal_id": key})
    if name == "atomic_failure":
        original_event = store.event

        def failing_event(event_name, **body):
            if event_name == "tool.allowed" and body.get("action") == "rollback.execute":
                raise OSError("Simulated audit write failure before commit")
            return original_event(event_name, **body)

        store.event = failing_event
        try:
            try:
                runtime.call(handle, "rollback.execute", {"proposal_id": key})
            except OSError:
                pass
            else:
                raise AssertionError("Fault injection did not run")
        finally:
            store.event = original_event
        expect(store.get("deployment", "checkout")["version"] == "v42", "Partial deployment write")
        expect(not store.all("execution"), "Partial execution record survived")
        expect(not any(e["event"] == "execution.completed" for e in store.events()),
               "Uncommitted execution event survived")
        return {"rollback_atomic": True, "injected_failure": "audit write before commit"}
    if name == "concurrent_retry":
        path = store.db.execute("PRAGMA database_list").fetchone()[2]
        barrier = Barrier(2)

        def worker():
            connection = Store(path)
            try:
                fresh = Runtime(connection)
                token = execution_session(fresh, proposal)
                barrier.wait(timeout=10)
                return fresh.call(token, "rollback.execute", {"proposal_id": key})
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            outcomes = [future.result(timeout=15) for future in futures]
        expect(sorted(item["replayed"] for item in outcomes) == [False, True],
               "Concurrent callers both executed or both replayed")
        expect(len(store.all("execution")) == 1 and sum(
            e["event"] == "execution.completed" for e in store.events()) == 1,
            "Concurrent invocation duplicated the side effect")
        return {"concurrent_callers": 2, "executions": 1, "replays": 1}
    if name == "expired_approval":
        runtime.clock = lambda: 10**12
    if name == "changed_proposal":
        store.put("proposal", key, {**proposal, "to_version": "v40"})
    if name == "workflow_mismatch":
        handle = runtime.session("carol", "remediator", "INC-OTHER", SCOPE, {"rollback.execute"})
    if name == "approver_revoked":
        runtime.users["bob"]["role"] = "viewer"
    if name == "stale_deployment":
        store.put("deployment", "checkout", {"scope": SCOPE, "version": "v43"})
    result = runtime.call(handle, "rollback.execute", {"proposal_id": key})
    if name in {"retry", "restart_retry"}:
        if name == "restart_retry":
            path = store.db.execute("PRAGMA database_list").fetchone()[2]
            reopened = Store(path)
            try:
                fresh = Runtime(reopened)
                retry = fresh.call(execution_session(fresh, proposal), "rollback.execute",
                                   {"proposal_id": key})
            finally:
                reopened.close()
        else:
            retry = runtime.call(handle, "rollback.execute", {"proposal_id": key})
        expect(retry["replayed"] and not result["replayed"], "Retry executed again")
        expect(len(store.all("execution")) == 1, "Duplicate execution record")
        expect(sum(e["event"] == "execution.completed" for e in store.events()) == 1,
               "Duplicate side effect")
        return {"executions": 1, "retry_replayed": True}
    raise AssertionError(f"Scenario unexpectedly reached execution: {name}")


def chunk_scenario(name, store):
    document = store.get("evidence", "runbook-checkout")
    if name == "chunk_provenance":
        counts = {}
        for strategy in STRATEGIES:
            chunks = chunk_document(document, strategy)
            expect(chunks, "No chunks")
            for chunk in chunks:
                expect(chunk.text == document["text"][chunk.start:chunk.end], "Wrong offsets")
                expect(chunk.scope == SCOPE and chunk.document_id == document["id"],
                       "Lost access metadata or provenance")
            counts[strategy] = len(chunks)
        return {"chunk_counts": counts}
    if name == "overlap":
        fixture = {**document, "text": "zero one two three four five six seven eight nine"}
        phrase = "four five"
        fixed = chunk_document(fixture, "fixed", size=5, overlap=2)
        sliding = chunk_document(fixture, "sliding", size=5, overlap=2)
        expect(not any(phrase in c.text for c in fixed), "Fixture did not cross boundary")
        expect(any(phrase in c.text for c in sliding), "Overlap failed to preserve phrase")
        return {"boundary_phrase": phrase, "fixed_found": False, "sliding_found": True}
    if name == "recursive_bound":
        chunks = chunk_document(document, "recursive", size=12, overlap=3)
        expect(all(len(c.text.split()) <= 12 for c in chunks), "Recursive chunk too large")
        return {"maximum_words": max(len(c.text.split()) for c in chunks)}
    if name == "prerequisites":
        hits = retrieve([document], "structure", "rollback prerequisites", top_k=1)
        expect(hits and all(p.lower() in hits[0]["text"].lower() for p in
               ["incompatible database migration", "healthy and available", "manager approval"]),
               "Missing prerequisite")
        return {"retrieved": hits[0]["id"]}
    if name == "parent_expansion":
        hits = retrieve([document], "parent_child", "rollback prerequisites", top_k=1, size=12)
        expect(hits and hits[0]["parent_id"], "Parent reference missing")
        expect("manager approval" in hits[0]["text"] and len(hits[0]["text"].split()) > 12,
               "Parent was not expanded")
        return {"parent_id": hits[0]["parent_id"], "words": len(hits[0]["text"].split())}
    logs = store.get("evidence", "logs-101")
    time_groups, trace_groups = event_chunks(logs), event_chunks(logs, "trace")
    expect(len(time_groups) == 2 and len(trace_groups) == 3, "Unexpected grouping")
    expect(any(len(g["records"]) == 2 and g["records"][0]["trace"] == "r2"
               for g in trace_groups), "Trace was split")
    expect(all(g["scope"] == SCOPE and all("record_index" in r for r in g["records"])
               for g in trace_groups), "Missing event provenance")
    return {"time_groups": len(time_groups), "trace_groups": len(trace_groups)}


def run_features(dataset=None):
    dataset = dataset or ROOT / "evals" / "features.json"
    cases = json.loads(Path(dataset).read_text(encoding="utf-8"))["cases"]
    results = []
    for case in cases:
        with TemporaryDirectory(prefix="incident-lab-eval-") as directory:
            store = Store(Path(directory) / "case.db")
            seed(store)
            runtime = Runtime(store)
            details, actual = {}, "ok"
            try:
                details = scenario(case["scenario"], store, runtime) or {}
            except Denied as exc:
                actual = str(exc)
                # All denied execution cases must have no completed execution.
                if store.all("execution"):
                    actual = "error: denied operation nevertheless executed"
            except Exception as exc:
                actual = f"error: {type(exc).__name__}: {exc}"
            finally:
                trace = store.events()
                store.close()
            results.append({**case, "actual": actual, "passed": actual == case["expected"],
                            "details": details, "trace": trace})
    return {"schema_version": 1, "dataset": str(dataset), "total": len(results),
            "passed": sum(r["passed"] for r in results), "results": results}


def run_retrieval():
    questions = json.loads((ROOT / "evals" / "retrieval.json").read_text())["questions"]
    store = Store()
    try:
        seed(store)
        runtime = Runtime(store)
        handle = runtime.session("alice", "researcher", "RETRIEVAL", SCOPE, {"docs.read"})
        # Authorization precedes chunking and retrieval; only these documents enter the index.
        documents = [runtime.call(handle, "docs.read", {"evidence_id": key}) for key in
                     ("runbook-checkout", "unrelated-incident")]
        results = []
        for strategy in STRATEGIES:
            for question in questions:
                hits = retrieve(documents, strategy, question["query"])
                text = " ".join(hit["text"].lower() for hit in hits)
                covered = [p for p in question["required_phrases"] if p.lower() in text]
                all_words = sum(len(h["text"].split()) for h in hits)
                unique_positions = {(h["document_id"], i) for h in hits
                                    for i in range(h["start"], h["end"])}
                total_positions = sum(h["end"] - h["start"] for h in hits)
                results.append({"strategy": strategy, "question_id": question["id"],
                    "document_hit": any(h["document_id"] == question["expected_document"] for h in hits),
                    "required_phrase_coverage": len(covered) / len(question["required_phrases"]),
                    "covered_phrases": covered, "context_words": all_words,
                    "irrelevant_document_hits": sum(h["document_id"] != question["expected_document"] for h in hits),
                    "duplicate_character_fraction": 1 - len(unique_positions) / total_positions
                        if total_positions else 0,
                    "retrieved_ids": [h["id"] for h in hits]})
        return {"schema_version": 1, "top_k": 2, "chunk_size_words": 35, "results": results}
    finally:
        store.close()
