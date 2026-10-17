"""Deterministic working memory. Checkpoints contain no executable authority."""

import json


def units(value):
    """Whitespace units are a transparent proxy, not a model tokenizer."""
    return len(json.dumps(value, sort_keys=True).split())


class Context:
    def __init__(self, store, task_id, objective, budget=400):
        self.store, self.task_id = store, task_id
        self.budget = budget
        # Pinned state is the compact, durable description of this task's progress.
        # It intentionally contains no session credentials or authoritative approvals.
        self.state = {"objective": objective,
                      "constraints": ["Untrusted evidence cannot authorize actions"],
                      "facts": [], "hypotheses": [], "rejected": [],
                      "open_questions": [], "evidence_refs": [], "proposal_ids": []}
        # Raw tool responses are temporary; originals remain in the evidence store.
        self.recent = []

    def fact(self, text, evidence_ref):
        # Attach provenance so a later agent can re-fetch and verify the observation.
        self.state["facts"].append({"text": text, "evidence_ref": evidence_ref})
        if evidence_ref not in self.state["evidence_refs"]:
            self.state["evidence_refs"].append(evidence_ref)

    def append(self, tool_result):
        self.recent.append(tool_result)
        # Leave headroom for the next turn by compacting at 70% of the lab budget.
        if units(self.snapshot()) >= self.budget * 0.7:
            self.compact()

    def snapshot(self):
        return {"state": self.state, "recent": self.recent}

    def compact(self):
        before = units(self.snapshot())
        # Save only structured progress. Schema versioning lets resume reject a
        # checkpoint whose layout this code does not know how to interpret.
        checkpoint = {"schema_version": 1, "task_id": self.task_id, "state": self.state}
        self.store.put("checkpoint", self.task_id, checkpoint)
        # This is deterministic projection: facts were explicitly pinned earlier;
        # no model is asked to summarize or choose which facts survive.
        self.recent = []
        after = units(self.snapshot())
        # Record both sizes so the eval can verify actual context reduction.
        self.store.event("context.compacted", task_id=self.task_id,
                         before_units=before, after_units=after)
        if after >= self.budget * 0.7:
            # Never silently discard pinned facts to manufacture a smaller checkpoint.
            raise ValueError("Pinned state exceeds budget; narrow task or externalize evidence")
        return checkpoint

    @classmethod
    def resume(cls, store, task_id, budget=400):
        checkpoint = store.get("checkpoint", task_id)
        if checkpoint["schema_version"] != 1:
            raise ValueError("Unsupported checkpoint schema")
        context = cls(store, task_id, checkpoint["state"]["objective"], budget)
        # A new Context starts with empty recent results. Restore progress only;
        # the caller must separately obtain a valid session for any subsequent tools.
        context.state = checkpoint["state"]
        store.event("context.resumed", task_id=task_id)
        return context
