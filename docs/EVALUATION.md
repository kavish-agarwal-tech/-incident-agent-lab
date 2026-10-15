# Evaluation set and baseline

## Run

```powershell
python -m incident_lab eval
python -m incident_lab eval --output artifacts/my-eval-report.json
```

The command runs two complementary datasets:

1. `evals/features.json`: 43 integration acceptance cases with exact expected
   outcomes and explicit assertions. Any failing case makes the command exit 1.
2. `evals/retrieval.json`: four golden questions evaluated across six document
   chunking strategies, producing 24 descriptive benchmark rows. These metrics
   are not pass/fail gates.

Each feature case receives fresh synthetic fixtures in a temporary on-disk SQLite
database. A case can reopen that database, use separate connections concurrently,
or launch separate CLI processes. It cannot leak state into another case.

## Coverage map

| Feature | Case IDs | What is checked |
|---|---|---|
| Complete workflow | `flow-01`, `flow-02` | Separate initiator/approver/executor; proposal-only default |
| Handoffs | `handoff-01` to `handoff-03` | Task schema, preserved initiator, grant ceiling, context isolation |
| Compaction | `ctx-01` to `ctx-03` | Critical state survives reopen; approval text has no authority; overflow is visible |
| User RBAC | `rbac-01`, `rbac-06`, `rbac-07` | Viewer denial, current-role revocation, grant issuance ceiling |
| Agent RBAC | `rbac-02` | Operator cannot execute through Investigator |
| Task and resource scope | `rbac-03` to `rbac-05` | Narrow grant, cross-tenant reference, production isolation |
| Tool boundaries | `tools-01` to `tools-06` | Filtered discovery, hidden invocation, spoofed args, fake handles, wrong resource type, call budget |
| Untrusted evidence | `security-01` | Malicious log content never grants authority or executes a tool |
| Approval | `approval-01` to `approval-07` | Missing, wrong role, expired, changed proposal, wrong workflow, revoked approver, no user elevation |
| Execution consistency | `exec-01` to `exec-06` | Retry, reopen, stale version, ID conflict, atomic failure, concurrent retry |
| Chunking | `chunk-01` to `chunk-06` | Provenance, boundary overlap, recursive bounds, prerequisites, parent expansion, event grouping |
| Audit | `audit-01` | Denial reason persisted with no execution |
| CLI process boundaries | `cli-01` | Proposal, denials, approve, execute, retry, trace across eight processes |

## Feature case format

```json
{
  "id": "approval-03",
  "feature": "approval",
  "scenario": "expired_approval",
  "expected": "approval_expired",
  "description": "Approval expiry is checked at execution."
}
```

`scenario` selects a concrete experiment in `evaluation.scenario`. There is no
dynamic Python evaluation of the JSON. Positive cases assert facts about outputs
and durable state. Negative cases compare stable denial codes, and the harness
also rejects denied cases that nevertheless left an execution record.

The report retains case metadata, expected and actual outcome, boolean pass,
assertion details and the ordered audit trace. Unexpected exceptions become failed
cases with their exception type and message; the runner continues to other cases.

## Retrieval case format and metrics

Each golden question supplies a query, expected document and required phrases.
Documents are fetched through the authorization gateway before indexing. Metrics:

- `document_hit`: any returned hit belongs to the expected document.
- `required_phrase_coverage`: fraction of golden phrases present in retrieved text.
- `context_words`: total whitespace-delimited words supplied by the hits.
- `irrelevant_document_hits`: hits from another document than the expected source.
- `duplicate_character_fraction`: fraction of returned source character positions
  repeated across hits from the same document; measures overlapping context.
- `retrieved_ids`: chunk IDs for inspection and provenance.

Required-phrase coverage measures retrieval completeness for this corpus, not
answer correctness or semantic recall. A rephrased valid passage may score poorly.
The document-hit metric alone cannot establish that all prerequisites were retrieved.

## Recorded initial baseline

Python 3.14.6 on Windows; deterministic lexical retrieval; top-k 2; 35-word child
chunks; eight-word sliding overlap. The final verification command produces the
current local report under `artifacts/`.

| Strategy | Mean required-phrase coverage across four questions |
|---|---:|
| Fixed | 0.75 |
| Sliding | 0.92 |
| Recursive | 0.83 |
| Structure | 1.00 |
| Semantic mock | 1.00 |
| Parent-child | 1.00 |

These are tiny-corpus observations, not a recommendation that one strategy always
wins. Larger sections return more context. Semantic mock shares fixture topic
boundaries with the structure splitter. Compare context cost and irrelevant hits
alongside coverage; do not read equal scores as equivalent implementations.

## Add a new eval

1. Add a synthetic input or controlled failure condition.
2. Add an explicit scenario branch and assertions in `evaluation.py`.
3. Add a stable case ID, feature tag, scenario name and expected outcome to JSON.
4. For a denial, assert no unauthorized output or state transition occurred.
5. Run the entire suite and inspect the case trace in the report.
6. Update this coverage map and explain any deliberate baseline change.

For a retrieval extension, add a new document and a golden question with source
and expected evidence phrases. Keep the same questions across all strategies.
Introduce a separately versioned quality threshold before making benchmark scores
release gates; this POC does not silently tune thresholds to pass current outputs.

## What is not established

Passing this suite validates the scripted flow and its local policy checks on the
defined cases. It does not prove general model reasoning, semantic summarization,
prompt-injection resistance, MCP interoperability, OAuth correctness, production
authentication, external-side-effect exactly-once behavior, or performance at scale.
The concurrency case covers two local SQLite callers, not distributed agent scheduling.
