# Context handoff, compaction and chunking

## Distinguish the mechanisms

| Mechanism | Purpose | POC example |
|---|---|---|
| Delegation | Ask a specialist to complete a bounded task | Coordinator asks Investigator to diagnose timeouts |
| Handoff | Transfer the next work stage with enough context to continue | Investigation evidence references pass to Remediator |
| Compaction | Reduce active working context without losing essential state | Discard large noisy log output after pinning facts |
| Chunking | Divide source material into retrievable units | Runbook sections or fixed-word windows |
| Retrieval | Select relevant authorized chunks for a question | Fetch complete rollback prerequisites |

## Handoff contract

`Runtime.delegate` persists an envelope containing task/workflow IDs, source and
destination agents, objective, constraints, evidence references, known facts,
open questions, completion criteria, and budgets. It does not forward a complete
transcript, credentials, user role claims, or an execution approval.

The envelope is task data. The separately issued session determines authority.
Child grants are constrained by the parent grant. Each session has an eight-call
tool budget; context objects use a 400-unit budget by default. These are fixed lab
defaults, not production tuning recommendations. Total workflow budgets, nested
delegation depth and scheduling deadlines are future work.

Each specialist context is a separate object. The sample aggregates structured
outputs in the trusted workflow rather than exposing a shared conversation to
every specialist. Authorized outputs can be shared intentionally; context isolation
does not mean evidence must never be shared.

## Compaction algorithm

1. Pin facts with source references, hypotheses, rejected explanations and open
   questions in structured working state.
2. Append raw tool output to `recent`.
3. Measure JSON whitespace units for state plus recent results.
4. At 70% of the configured budget, persist a versioned checkpoint.
5. Empty the raw recent-result list. Keep originals in durable evidence storage.
6. Resume a fresh Context object from the checkpoint, including after DB reopen.

Preserved fields include the objective, constraints, facts, hypotheses, rejected
explanations, open questions, evidence references and proposed action IDs. The
workflow pins facts before adding its deliberately large noisy tool response.

This compaction is deterministic state projection, not an LLM summary. If pinned
state itself exceeds the threshold, the operation raises an explicit error instead
of silently truncating facts. The checkpoint remains available for inspection;
the caller must narrow the task or externalize additional state.

`units` is a readable size proxy. Replace it with a real tokenizer when introducing
models. The current API first receives the full local tool result; it is not a
streaming defense against oversized external payloads.

Authority is always re-read from the runtime and approval store. Even a checkpoint
containing `approved: true` grants no execution rights.

Context compaction, external notes and specialist contexts follow the general
patterns described in [Anthropic's context engineering article](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).

## Chunk strategies

The lab uses words rather than tokens. Default lexical retrieval uses chunks of
35 words, eight-word sliding overlap, and the top two distinct hits. Not every
strategy imposes the same size limit; preserving complete sections is intentional.

| Strategy | Implementation | Tradeoff to observe |
|---|---|---|
| `fixed` | Nonoverlapping word windows | Small but may cut a condition in half |
| `sliding` | Overlapping word windows | Better boundary coverage; duplicated context |
| `recursive` | Try paragraphs, lines, sentence separators, then word windows | Preserves natural boundaries while bounding size |
| `structure` | Markdown heading sections | Complete procedures; variable chunk sizes |
| `semantic_mock` | Author-supplied topic spans, defaulting to headings | Demonstrates topic grouping without semantic inference |
| `parent_child` | Search short section children; expand the matched parent section | Precise matching with more complete surrounding context |

`event_chunks` additionally supports fixed time buckets and trace grouping. Log
chunks retain original record indices, timestamps and scope. Time buckets can
split a trace at a bucket boundary; trace grouping reconstructs a request across
records. These are distinct from overlapping document windows.

Semantic mock and structure produce the same results on the default corpus because
topic boundaries coincide with headings. This is not evidence that semantic
models and heading splitters perform equally.

Chunk selection should be evaluated against the actual corpus and questions, as
discussed in [Microsoft's RAG chunking guidance](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-chunking-phase).

## Provenance and permissions

Every document chunk carries document ID, unique chunk ID, exact character offsets,
source text, scope labels, and optional parent ID/offsets. The source document
remains the authority for access labels. Event chunks retain record indices.

The benchmark fetches documents through `docs.read` before indexing. Retrieval
accepts only those already-authorized documents and expands parents from that same
authorized set. `retrieve` is a pure transformation, not an authorization gateway.
Do not expose it as an unrestricted document-fetch API. A future persistent shared
index must enforce ACL filtering and parent authorization at query/fetch time.

## Experiments

1. Lower `Context`'s budget and inspect compaction events and pinned-state overflow.
2. Add a critical fact near the end of noisy evidence. Pin it and confirm resume
   retains it; omit pinning to observe the limitation of this deterministic method.
3. Add a cross-tenant evidence reference to a handoff and fetch it with the child:
   the reference must not bypass scope checks.
4. Move a runbook prerequisite across a fixed-word boundary. Compare fixed and sliding.
5. Increase overlap and inspect duplicate-character fraction and context words.
6. Make a parent section much longer. Observe parent-child context cost.
7. Add topic spans that differ from headings to make `semantic_mock` behave differently.
8. Add a request spanning a time-bucket boundary and compare time versus trace grouping.
