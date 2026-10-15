# POC scope and learning objectives

## Goal

Make multi-agent mechanics observable without requiring an LLM or external tool
server. Use a meaningful incident response scenario and enforce permissions in
ordinary application code. This document captures the agreed scope, including the
later requirement for a reusable eval set.

## Use case

Checkout errors increase from 1% to 35% after deployment v42. Logs show connection
timeouts; deployment metadata shows the connection pool changed from 50 to 2.
A runbook describes rollback prerequisites and recovery. This supports a
configuration-regression hypothesis, not a proven root cause.

The coordinator delegates investigation and document reading, then transfers the
recovery proposal to a remediator. Alice is a Responder, Bob an Incident Manager,
Carol an Operator, and Victor a Viewer. Only tenant-a / checkout / staging is
authorized for these users. Another tenant's evidence is deliberately present.

## Implemented scope

| Capability | Observable behavior | Main reference |
|---|---|---|
| Delegation and handoff | Structured bounded envelopes, evidence references, separate specialist contexts | `Runtime.delegate`, `workflow.investigate` |
| Context compaction | 70% trigger, structured checkpoint, discarded noisy results, durable resume | `Context` |
| Agent tool scope | Filtered discovery plus independent invocation checks | `Runtime.list_tools`, `Runtime.call` |
| User + agent RBAC | Intersection of current user rights, agent rights, and task grant | `Runtime.check` |
| Resource constraints | Exact tenant/service/environment and workflow checks | `Runtime.check`, `_execute` |
| Action approval | Separate approver, exact-proposal hash, expiry and approver revalidation | `Runtime.approve`, `_execute` |
| Replay safety | Atomic simulated write and execution record; durable idempotency | `Store.transaction`, `_execute` |
| Chunking | Fixed, sliding, recursive, structure, mocked semantic, parent-child, event grouping | `chunking.py` |
| Trust boundaries | Malicious evidence stays data; evidence does not mint sessions or approvals | `runtime.py`, feature evals |
| Observability | Ordered audit events, durable findings, JSON eval reports | `Store`, `evaluation.py` |
| Eval set | Expected outcomes for feature scenarios plus golden retrieval questions | `evals/` |

The implementation is a sequential orchestrated workflow. Separate agent roles and
contexts demonstrate multi-agent boundaries; parallel agent scheduling is not
required to learn these boundaries.

## Acceptance criteria

1. Default demo creates an evidence-backed proposal without executing it.
2. Full scripted demo preserves Alice/Bob/Carol attribution.
3. Each task receives only its objective, references, constraints and budget.
4. Compaction retains facts, uncertainty, decisions and original source references.
5. Checkpoint content never substitutes for trusted authorization state.
6. User, agent, task, tenant, environment, and approval denials are observable.
7. A repeated execution after reopening SQLite has one completed side effect.
8. Chunking strategies retain source provenance and are compared on fixed questions.
9. Feature eval failures cause a nonzero exit code and explain expected vs actual.
10. Architecture, flow, experiments, and limitations remain documented in Git.

## Deliberate simplifications

- Agents are deterministic Python decisions, not model calls or independent OS processes.
- One role and one exact resource scope per fixture user. Multiple roles, groups,
  hierarchy, wildcard resources, and policy inheritance are future work.
- Session handles simulate authenticated identities inside a trusted local process.
  The CLI's `--user` selects a fixture actor, not a verified identity.
- MCP discovery/invocation is modeled in process. No actual MCP protocol, OAuth,
  remote server, or credential issuance is implemented.
- Context size uses JSON whitespace units, not a tokenizer. Compaction pins known
  structured facts and drops raw noise; it does not assess model-written summaries.
- Semantic chunking uses author-supplied topic spans, defaulting to section spans.
  It is explicitly labeled `semantic_mock`.
- Retrieval is lexical term overlap. No embeddings, vector index, reranking, or LLM answer generation.
- The local database and code are trusted. Direct DB editing, arbitrary Python
  execution, and malicious OS users are outside the enforcement boundary.
- Audit events are ordered and durable, not cryptographically tamper evident.
- Crash recovery guarantees concern a SQLite state change. Real external side
  effects require remote idempotency support or reconciliation/outbox design.
- No real remediation, outbound communication, or secret export tool exists.

## Next iterations

1. Swap deterministic specialist decisions for a pluggable model adapter; reuse the gateway.
2. Evaluate real summary fidelity and prompt injection with repeated adversarial model runs.
3. Add an actual MCP adapter while keeping server-side authorization checks.
4. Replace fixture users with authenticated principals and an external policy store.
5. Add configurable multi-role policy, explicit capability grants, and grant revocation.
6. Add concurrent scheduling, cancellation, bounded delegation depth and total workflow budgets.
7. Expand retrieval fixtures, semantic boundary models, and answer-grounding evaluation.

No hosted repository or remote is required for this local POC. Publishing can be a
separate step once a destination is chosen.
