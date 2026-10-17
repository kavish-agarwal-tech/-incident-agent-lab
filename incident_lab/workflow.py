"""Explicit, deterministic agent decisions make mechanics reproducible."""

from .context import Context
from .fixtures import SCOPE
from .runtime import Denied, Runtime


def investigate(runtime, workflow_id="INC-101"):
    store = runtime.store
    # Stage 1: Alice starts an investigation. Her delegation ceiling permits reads
    # and proposal creation, but deliberately excludes execution and approval.
    grant = {"logs.read", "metrics.read", "deployments.read", "docs.read", "rollback.propose"}
    lead = runtime.session("alice", "coordinator", workflow_id, SCOPE, grant)
    # Stage 2: Give the Investigator only its diagnostic task and read permissions.
    # The returned handle carries authority; task is the separate handoff envelope.
    investigator, task = runtime.delegate(
        lead, "investigator", workflow_id + ":logs", "Diagnose checkout failures",
        {"logs.read", "metrics.read", "deployments.read"}, ["logs-101", "deployment-v42"],
    )
    # Every evidence read goes through the gateway, including reads by specialists.
    logs = runtime.call(investigator, "logs.read", {"evidence_id": "logs-101"})
    metrics = runtime.call(investigator, "metrics.read", {"evidence_id": "metrics-101"})
    deployment = runtime.call(investigator, "deployments.read", {"evidence_id": "deployment-v42"})
    # Stage 3: Pin important observations before raw results consume the context.
    # This lab scripts the interpretation; an LLM adapter would replace this block.
    context = Context(store, task["task_id"], task["objective"])
    context.fact("Database connection timeouts occur after v42", "logs-101")
    context.fact("Error rate increased from 1% to 35%", "metrics-101")
    context.fact("v42 reduced connection pool from 50 to 2", "deployment-v42")
    # Keep observations distinct from a possible cause and unverified recovery.
    context.state["hypotheses"] = ["v42 pool configuration caused checkout failures"]
    context.state["open_questions"] = ["Will rollback restore the error rate?"]
    context.state["rejected"] = ["No evidence yet supports an image cache problem"]
    # A noisy response forces the deliberately small context budget to compact.
    context.append({"logs": logs, "metrics": metrics, "deployment": deployment,
                    "diagnostic_noise": "irrelevant historical entry " * 180})
    # Drop this Context reference to demonstrate reconstructing working memory
    # from the saved checkpoint rather than reusing its in-memory conversation.
    del context
    resumed = Context.resume(store, task["task_id"])
    # Stage 4: The Researcher gets a separate document-only task and session.
    researcher, _ = runtime.delegate(
        lead, "researcher", workflow_id + ":runbook", "Check recovery prerequisites",
        {"docs.read"}, ["runbook-checkout"],
    )
    runbook = runtime.call(researcher, "docs.read", {"evidence_id": "runbook-checkout"})
    # Check fixture recovery prerequisites before recommending the rollback.
    # Reading an approval instruction is not the same as obtaining an approval.
    if deployment["incompatible_migration"] or not deployment["v41_available"]:
        raise Denied("rollback_prerequisites")
    if "Obtain incident manager approval" not in runbook["text"]:
        raise Denied("missing_runbook_prerequisite")
    # Stage 5: Transfer the next stage to Remediator using compacted evidence refs.
    # Its narrow grant allows a proposal, not execution of that proposal.
    remediator, _ = runtime.delegate(
        lead, "remediator", workflow_id + ":proposal", "Propose the bounded recovery action",
        {"rollback.propose"}, resumed.state["evidence_refs"],
    )
    proposal = runtime.call(remediator, "rollback.propose", {
        "action_id": workflow_id + ":rollback", "incident": workflow_id,
        "from_version": "v42", "to_version": "v41",
    })
    # Retain a readable finding for later review. No post-rollback metrics exist,
    # so creating or executing the proposal must not mark the incident recovered.
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
    # The default learning flow stops before a human decision or deployment write.
    runtime = Runtime(store)
    proposal = investigate(runtime, workflow_id)
    result = {"proposal": proposal, "status": "awaiting_human_approval"}
    if execute:
        # Explicit demo mode impersonates fixture users, not real authenticated people.
        runtime.approve("bob", proposal["action_id"])
        # Carol's new task supplies execution rights; Alice remains the originator.
        handle = execution_session(runtime, proposal)
        result["execution"] = runtime.call(handle, "rollback.execute",
                                           {"proposal_id": proposal["action_id"]})
        result["status"] = "simulated_rollback_complete_verification_pending"
    return result
