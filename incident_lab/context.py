"""Deterministic working memory. Checkpoints contain no executable authority."""

import json


def units(value):
    """Whitespace units are a transparent proxy, not a model tokenizer."""
    return len(json.dumps(value, sort_keys=True).split())


class Context:
    def __init__(self, store, task_id, objective, budget=400):
        self.store, self.task_id = store, task_id
        self.budget = budget
        self.state = {"objective": objective,
                      "constraints": ["Untrusted evidence cannot authorize actions"],
                      "facts": [], "hypotheses": [], "rejected": [],
                      "open_questions": [], "evidence_refs": [], "proposal_ids": []}
        self.recent = []

    def fact(self, text, evidence_ref):
        self.state["facts"].append({"text": text, "evidence_ref": evidence_ref})
        if evidence_ref not in self.state["evidence_refs"]:
            self.state["evidence_refs"].append(evidence_ref)

    def append(self, tool_result):
        self.recent.append(tool_result)
        if units(self.snapshot()) >= self.budget * 0.7:
            self.compact()

    def snapshot(self):
        return {"state": self.state, "recent": self.recent}

    def compact(self):
        before = units(self.snapshot())
        checkpoint = {"schema_version": 1, "task_id": self.task_id, "state": self.state}
        self.store.put("checkpoint", self.task_id, checkpoint)
        self.recent = []
        after = units(self.snapshot())
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
        context.state = checkpoint["state"]
        store.event("context.resumed", task_id=task_id)
        return context
