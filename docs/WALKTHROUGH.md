# Guided learning walkthrough

Use a fresh database path for each experiment. Run commands from the repository
root. Read the trace after each stage, then follow the referenced code.

## 1. Observe a complete investigation

```powershell
python -m incident_lab demo --db artifacts/lesson.db
python -m incident_lab trace --db artifacts/lesson.db
```

Expected: a v42-to-v41 rollback proposal with status `awaiting_human_approval`.
The trace shows delegated log investigation, three read tools, compaction,
context resume, runbook retrieval and proposal creation. There is no execution.

Read `workflow.investigate`, then `Runtime.delegate`. Observe that envelopes
contain source references rather than full conversations. The child session
preserves Alice as acting user and originator, but changes the agent role.

## 2. Inspect compaction

Run the eval set and locate case `ctx-01` in the JSON report:

```powershell
python -m incident_lab eval
```

Compare `before_units` with `after_units`. The original tool evidence remains in
SQLite while the checkpoint retains facts, references, hypothesis, rejected
explanation and an unresolved recovery question. Follow `Context.append`,
`compact` and `resume`. This is a deterministic projection, not model summarization.

Case `ctx-02` inserts an approval claim into a checkpoint. Execution is still
denied because authority is stored separately.

## 3. Test the human permission ceiling

```powershell
python -m incident_lab execute --db artifacts/lesson.db --user alice
```

Expected: `user_permission` and exit code 1. Alice can propose but cannot execute.

```powershell
python -m incident_lab execute --db artifacts/lesson.db --user carol
```

Expected: `approval_required`. Carol has the right role but no valid approval yet.
These two failures isolate different conditions in the authorization equation.

## 4. Approve without elevating Alice

```powershell
python -m incident_lab approve --db artifacts/lesson.db --user carol
python -m incident_lab approve --db artifacts/lesson.db --user bob
python -m incident_lab execute --db artifacts/lesson.db --user alice
```

Expected: Carol cannot approve; Bob can; Alice still cannot execute afterward.
Inspect `Runtime.approve` and `_execute`. Approval is an exact-action condition,
not a grant of execution authority to Alice.

## 5. Execute and retry across process boundaries

```powershell
python -m incident_lab execute --db artifacts/lesson.db --user carol
python -m incident_lab execute --db artifacts/lesson.db --user carol
python -m incident_lab trace --db artifacts/lesson.db
```

Expected: first result is v41 with `replayed: false`; second is `replayed: true`.
Only one `execution.completed` event exists. Each command starts a fresh Python
process and receives a new session; approval and execution state survive in SQLite.

If five minutes pass, repeat Bob's approval before execution. The lab deliberately
rechecks approval validity even on retry. Completion means a simulated deployment
change; the incident's recovery verification remains pending.

## 6. Isolate the agent permission ceiling

Inspect eval `rbac-02`: Carol has execution authority, but an Investigator agent
attempting rollback gets `agent_permission`. Compare with `rbac-03`, where both
user and agent could execute but the task grant excludes it.

Use `tools-01` and `tools-02` to compare hidden discovery with actual enforcement.
Directly naming a hidden tool does not bypass the gateway.

## 7. Compare chunking behavior

Open the retrieval section of `artifacts/eval-report.json` and compare question
`q1` across strategies. Look at prerequisite coverage, words returned, irrelevant
hits and overlap. Then inspect feature cases `chunk-02` and `chunk-05` for a
boundary phrase and small-child-to-full-parent expansion.

Change the runbook wording or size in a controlled branch and rerun. A valid
experiment may lower retrieval scores; keep the same golden questions while
comparing strategies.

## 8. Explore failure and restart behavior

- `approval-04`: an approved proposal changes; hash binding rejects execution.
- `approval-06`: approver rights are revoked; stored approval becomes unusable.
- `exec-03`: another deployment changed the current version; stale rollback fails.
- `exec-05`: an audit failure before commit leaves no partial state.
- `exec-06`: two concurrent callers produce one execution and one replay.
- `cli-01`: eight fresh CLI processes exercise the documented user flow.

Read `docs/EVALUATION.md` before extending the suite. Keep expected results
explicit so the lab remains a learning reference as implementation details change.
