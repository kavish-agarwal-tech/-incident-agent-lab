# User RBAC, agent RBAC, resource scope and approval

## Authorization equation

```text
Allow tool invocation =
    current user permits action
    AND agent role permits action
    AND task grant permits action
    AND user scope = task scope = resource scope
    AND workflow matches the proposal, for rollback execution
    AND exact, unexpired approval is valid, if required
```

Rights from different principals are never unioned together. An approval does not
add execution rights to the initiating user.

## Identity and authority

| Identity | Meaning | Example |
|---|---|---|
| Originating user | Who initiated the business request | Alice |
| Acting user | Whose permissions authorize this task | Alice during investigation; Carol during execution |
| Agent | Which responsibility is performing the action | Investigator, Researcher, Remediator |
| Approver | Who authorized the exact proposed action | Bob |

The trusted host creates an opaque session handle. Internally it binds the acting
user, agent role, workflow, originator, resource scope and action grant. The agent
cannot set these values via tool arguments or a handoff message. The gateway
resolves the handle and checks current user rights on every call.

The fixture CLI is the trusted host. Selecting `--user bob` is an impersonation
control for learning, not authentication. In a real service, replace this with
verified login claims and server-side role lookup; do not trust a request body
that asserts a user or role.

## User roles

| Role | Read logs/metrics/deployments/docs | Propose rollback | Execute rollback | Approve rollback |
|---|---|---|---|---|
| Viewer / Victor | Yes | No | No | No |
| Responder / Alice | Yes | Yes | No | No |
| Operator / Carol | Yes | Yes | Yes | No |
| Incident Manager / Bob | Yes | No | No | Yes |

## Agent roles

| Agent | Allowed actions |
|---|---|
| Coordinator | Delegate narrower task grants |
| Investigator | `logs.read`, `metrics.read`, `deployments.read` |
| Researcher | `docs.read` |
| Remediator | `docs.read`, `rollback.propose`, `rollback.execute` |

Permissions are declarative sets in `fixtures.py`. The runtime is deny-by-default
for unknown identities, unknown tools, mismatched schemas and missing grants.
Each user currently has exactly one role. The design can later support multiple
roles by unioning roles **within the same principal**, then intersecting the user,
agent and grant dimensions.

## Delegation is not privilege inheritance

Alice's coordinator has a task grant covering investigation, document reading and
proposal creation. Its own agent role cannot directly perform those specialist
tool operations. It delegates subsets to specialists whose own roles permit them.

The coordinator cannot delegate rollback execution because Alice has no execution
right and the parent's task grant excludes it. The child session retains Alice's
identity and resource scope. A document reference in the handoff must still pass
the recipient's access checks when fetched.

`delegate` is a runtime control operation restricted to the coordinator role,
not a domain tool or a user permission that adds business authority. Session and
delegation creation are trusted harness operations in this version.

## Discovery versus enforcement

`list_tools` filters tools using user rights, agent rights and the task grant.
Hiding a tool improves the agent interface but is not the security boundary.
`call` independently checks its schema, identities, rights, resource and approval.

Argument keys are exact, values are nonempty strings of bounded length, and
fields such as `user`, `role`, `approved`, and `scope` cannot be added to a tool call.
Resource scope comes from trusted evidence and session metadata.

## Approval and execution

1. Alice's Remediator proposes v42 to v41 in INC-101.
2. Bob's human approval entry point checks approval rights, scope and separation
   from the proposer.
3. The store records the complete proposal's canonical SHA-256 hash, Bob's identity
   and an expiry. This is an integrity binding against API-level proposal changes,
   not a cryptographic defense against someone who can edit the database.
4. Carol starts a separate Remediator task under her Operator rights. Alice remains
   recorded as originator; Alice's own session is never upgraded.
5. The gateway revalidates Carol, the agent, grant, scope, workflow, approval hash,
   expiry and Bob's current approval rights.
6. It checks the simulated current version and atomically executes or replays.

An approval is reusable only for retrying the exact bound action. A retry still
requires current execution and approval authority. A new target, incident or scope
requires a new proposal and approval. There is no implicit approval-based privilege
elevation and no service-account execution path in this version.

## What the evals establish

Negative cases cover user and agent ceilings independently, narrower grants,
cross-tenant reads, staging/production isolation, hidden tool invocation, argument
spoofing, revocation, approval absence/expiry/tampering, and approval without user
privilege elevation. Execution cases cover retries, reopening SQLite, concurrent
callers, stale state, conflicting proposal IDs, and a failure before commit.

The malicious-log case establishes that scripted evidence handling does not mint
authority or invoke a nonexistent secret export tool. It does not establish that
a future model will resist every prompt injection. Keep gateway enforcement even
after adding models.

## Explicit trust boundary

Trusted: host entry points, policy configuration, runtime session map, Python
process, SQLite state and underlying filesystem. Untrusted: tool argument values,
retrieved text, handoff content, checkpoints and model-generated output.

Compaction cannot write approvals. A future model adapter should receive only
narrow callbacks, not the store or runtime object. Production deployments also
need authentication, session expiry, secure credential storage, isolated tool
execution, grant lifecycle management, and tamper-resistant audit storage. These
are extensions rather than claims of this simulation.
