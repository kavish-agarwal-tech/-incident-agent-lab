"""Explicit, deterministic agent decisions make mechanics reproducible."""

from .context import Context
from .fixtures import SCOPE
from .runtime import Denied, Runtime


def investigate(runtime, workflow_id="INC-101"):
    store = runtime.store
    grant = {"logs.read", "metrics.read", "deployments.read", "docs.read", "rollback.propose"}
    lead = runtime.session("alice", "coordinator", workflow_id, SCOPE, grant)
    investigator, task = runtime.delegate(
        lead, "investigator", workflow_id + ":logs", "Diagnose checkout failures",
        {"logs.read", "metrics.read", "deployments.read"}, ["logs-101", "deployment-v42"],
    )
    logs = runtime.call(investigator, "logs.read", {"evidence_id": "logs-101"})
    metrics = runtime.call(investigator, "metrics.read", {"evidence_id": "metrics-101"})
    deployment = runtime.call(investigator, "deployments.read", {"evidence_id": "deployment-v42"})
    context = Context(store, task["task_id"], task["objective"])
    context.fact("Database connection timeouts occur after v42", "logs-101")
    context.fact("Error rate increased from 1% to 35%", "metrics-101")
    context.fact("v42 reduced connection pool from 50 to 2", "deployment-v42")
    context.state["hypotheses"] = ["v42 pool configuration caused checkout failures"]
    context.state["open_questions"] = ["Will rollback restore the error rate?"]
    context.state["rejected"] = ["No evidence yet supports an image cache problem"]
    # A noisy response forces the deliberately small context budget to compact.
    context.append({"logs": logs, "metrics": metrics, "deployment": deployment,
                    "diagnostic_noise": "irrelevant historical entry " * 180})
    del context
    resumed = Context.resume(store, task["task_id"])
    researcher, _ = runtime.delegate(
        lead, "researcher", workflow_id + ":runbook", "Check recovery prerequisites",
        {"docs.read"}, ["runbook-checkout"],
    )
    runbook = runtime.call(researcher, "docs.read", {"evidence_id": "runbook-checkout"})
    if deployment["incompatible_migration"] or not deployment["v41_available"]:
        raise Denied("rollback_prerequisites")
    if "Obtain incident manager approval" not in runbook["text"]:
        raise Denied("missing_runbook_prerequisite")
    remediator, _ = runtime.delegate(
        lead, "remediator", workflow_id + ":proposal", "Propose the bounded recovery action",
        {"rollback.propose"}, resumed.state["evidence_refs"],
    )
    proposal = runtime.call(remediator, "rollback.propose", {
        "action_id": workflow_id + ":rollback", "incident": workflow_id,
        "from_version": "v42", "to_version": "v41",
    })
    store.put("finding", workflow_id, {
        "hypothesis": resumed.state["hypotheses"][0],
        "evidence_refs": resumed.state["evidence_refs"] + ["runbook-checkout"],
        "open_questions": resumed.state["open_questions"],
        "proposal_id": proposal["action_id"], "verification": "pending; no post-rollback metrics supplied",
    })
    return proposal


def execution_session(runtime, proposal):
    # Carol starts a new task under her own authority; Alice's session is not upgraded.
    return runtime.session("carol", "remediator", proposal["incident"], proposal["scope"],
                           {"rollback.execute"}, originator=proposal["proposed_by"])


def demo(store, execute=False, workflow_id="INC-101"):
    runtime = Runtime(store)
    proposal = investigate(runtime, workflow_id)
    result = {"proposal": proposal, "status": "awaiting_human_approval"}
    if execute:
        # Explicit demo mode impersonates fixture users, not real authenticated people.
        runtime.approve("bob", proposal["action_id"])
        handle = execution_session(runtime, proposal)
        result["execution"] = runtime.call(handle, "rollback.execute",
                                           {"proposal_id": proposal["action_id"]})
        result["status"] = "simulated_rollback_complete_verification_pending"
    return result
