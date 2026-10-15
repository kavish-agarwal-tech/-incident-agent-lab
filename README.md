# Incident Agent Learning Lab

A local, deterministic POC for learning multi-agent context management, tool scope,
user and agent RBAC, approval-controlled actions, and retrieval chunking.

**Scenario:** checkout errors rise after deployment v42 reduces the connection pool.
Agents inspect synthetic evidence, consult a runbook, and propose rollback to v41.
Alice proposes, Bob approves, and Carol executes a simulated staging rollback.

Requires Python 3.11+ and Git. No dependencies, API keys, model, Docker, or network.
Run all commands from this repository's root. The CLI uses named fixture users;
it does not authenticate real people. All deployment changes affect local SQLite only.

## Start here

```powershell
python -m incident_lab demo
```

This investigates, hands off work, forces compaction, resumes from the checkpoint,
and creates a proposal. It stops at `awaiting_human_approval`; deployment stays v42.

Try execution before approval; it should exit with code 1 and `approval_required`:

```powershell
python -m incident_lab execute --user carol
```

Approve and execute in separate processes:

```powershell
python -m incident_lab approve --user bob
python -m incident_lab execute --user carol
python -m incident_lab execute --user carol
python -m incident_lab trace
```

The first execution changes simulated deployment state to v41. The second returns
`replayed: true` without another side effect. Approval lasts five minutes; a retry
still checks current permissions and approval validity. Reapprove if it expires.
The incident stays open: no post-rollback metrics have been supplied.

For a complete scripted demonstration on a separate database:

```powershell
python -m incident_lab demo --execute --db artifacts/scripted.db
```

`--execute` explicitly simulates both Bob's approval and Carol's execution. It does
not represent real human consent. Use a new `--db` path for a fresh experiment;
existing databases retain execution and deployment state.

## Run the eval set

```powershell
python -m incident_lab eval
```

Exit code 0 means all feature evals passed; code 1 means at least one failed.
The report at `artifacts/eval-report.json` contains expected/actual outcomes,
assertion evidence, per-case audit traces, and retrieval metrics. Each feature
case gets an isolated temporary SQLite database. Reports and databases are ignored
by Git so rerunning experiments does not change source files.

## Reference documents

| Document | Read it for |
|---|---|
| [Scope](docs/SCOPE.md) | Learning objectives, implemented scope, limitations, roadmap |
| [Architecture](docs/ARCHITECTURE.md) | Component boundaries, durable state, sequence diagrams |
| [Authorization](docs/AUTHORIZATION.md) | User + agent roles, grants, scope, approvals, identity propagation |
| [Context and chunking](docs/CONTEXT_AND_CHUNKING.md) | Handoffs, checkpoints, retrieval strategies, experiment ideas |
| [Evaluation guide](docs/EVALUATION.md) | Dataset format, coverage, metrics, baseline, adding cases |
| [Walkthrough](docs/WALKTHROUGH.md) | A guided learning sequence and expected observations |

## Source map

```text
incident_lab/
  __main__.py    CLI and fixture-user entry points
  fixtures.py    Synthetic evidence and permission configuration
  runtime.py     Trusted sessions, delegation, policy gateway, approvals, tools
  store.py       SQLite object store, transactions, ordered audit events
  context.py     Per-agent working state, compaction, durable resume
  chunking.py    Six document strategies plus time/trace event grouping
  workflow.py    Deterministic coordinator and specialist flow
  evaluation.py  Feature scenarios and retrieval benchmark runner
evals/
  features.json  Versioned acceptance cases
  retrieval.json Golden retrieval questions and required phrases
docs/            Architecture and learning references
```

This is a learning harness, not a production security boundary or an LLM quality
benchmark. Its MCP-like adapter models discovery and invocation without actual
MCP transport or OAuth.
