# L0 Company Context — Acceptance Contract

**Component:** AI-Dev-Company Company OS  
**Context level:** L0 — Company Identity and Operating Policies  
**Contract version:** 1.1  
**Implementation:** `company_os/context/l0_company_context.py`  
**Policy catalog:** `company_os/context/company_policies.py`  
**Specialist specifications:** `agents/<specialist-slug>/agent.yaml`  
**Automated tests:** `tests/test_l0_company_context.py`

---

## 1. Purpose

L0 provides the minimum authoritative company context required by all later
project and specialist context levels.

It establishes company identity, project identity, the canonical eight-agent
roster, company operating policies, specialist specification readiness,
storage boundaries and validation evidence.

L0 does not activate agents or execute tasks.

## 2. Authoritative Company Identity

The Company Registry is authoritative.

| Field | Required value |
|---|---|
| Company ID | `co_ai_dev_company` |
| Slug | `ai-dev-company` |
| Name | `AI Software Engineering Company` |
| Required status | `active` |

Owner contact details must not be included in a public context packet.

The compiler must refuse compilation when Foundation validation fails.

## 3. Authoritative Project Identity

| Field | Required value |
|---|---|
| Project ID | `prj_ai_dev_company` |
| Company ID | `co_ai_dev_company` |
| Slug | `ai-dev-company` |
| Name | `AI-Dev-Company` |
| Repository | `https://github.com/imperiumsandy-commits/AI-Dev-Company` |
| Default branch | `main` |
| Required status | `active` |

The compiler must not silently substitute a different company, repository
or branch.

## 4. Canonical Specialist Roster

The canonical registry catalog contains exactly these specialists:

| ID | Specialist | Slug |
|---|---|---|
| `agent_business_analyst_pm` | Business Analyst / PM | `business-analyst-pm` |
| `agent_system_architect` | System Architect | `system-architect` |
| `agent_backend_developer` | Backend Developer | `backend-developer` |
| `agent_frontend_developer` | Frontend Developer | `frontend-developer` |
| `agent_database_administrator` | Database Administrator | `database-administrator` |
| `agent_cybersecurity_engineer` | Cybersecurity Engineer | `cybersecurity-engineer` |
| `agent_qa_bug_hunter` | QA / Bug Hunter | `qa-bug-hunter` |
| `agent_devops_engineer` | DevOps Engineer | `devops-engineer` |

Exactly eight unique registry records must exist and match the canonical
catalog. Missing or additional agents must cause validation failure.

Registration, specification readiness, runtime readiness, evaluation and
activation are separate states.

## 5. Specialist Specification Readiness

Each specialist has an independent canonical manifest:

`agents/<specialist-slug>/agent.yaml`

The file is a JSON document using the JSON-compatible subset of YAML 1.2.
This allows strict standard-library parsing without a runtime YAML dependency.

The manifest is required to contain:

- Canonical registry agent ID, slug, display name, role version and domain.
- Domain-specific mission, ownership and non-ownership boundaries.
- Inputs, outputs and handoff contracts.
- Architecture components, data objects and invariants.
- Workflow stages and explicit stop conditions.
- Allowed capability declarations and mandatory forbidden actions.
- Domain-specific quality gates.
- Memory ownership, persistence and resume rules.
- Failure modes, response and escalation behaviour.
- Independent evaluation scenarios.
- Explicit specification/runtime/evaluation/activation state.

The loader must validate the manifest against the registry catalog.

It must reject:

- Unknown or mismatched agent identity.
- A manifest with different capabilities from the canonical registry.
- Missing required architecture or workflow sections.
- Missing mandatory restrictions.
- Invalid JSON/YAML-subset content.
- Oversized or unreadable manifest files.
- A manifest that claims runtime implementation, completed evaluation
  or active execution when those capabilities are not implemented.

The L0 compiler reports the repository-relative specification directory,
readiness, loaded specification files, missing files and manifest digest.

A validated manifest means `specification_ready`. It does not mean the
agent is executable or active.

## 6. Company Operating Policies

The canonical policy catalog version is `1.1.0` and contains ten policies.

| Policy ID | Required subject |
|---|---|
| `company.project_separation` | Keep independent company projects separate |
| `company.specialist_independence` | Preserve eight specialist domains |
| `engineering.evidence_before_completion` | Evidence before completion |
| `engineering.first_pass_excellence` | First-pass, complete-batch, production-minded engineering |
| `delivery.github_is_source_of_truth` | GitHub-first source delivery |
| `security.credential_boundary` | Keep credentials outside ordinary storage and context |
| `governance.high_risk_owner_approval` | Owner approval for high-risk operations |
| `truth.registration_is_not_activation` | Report registration and activation truthfully |
| `memory.context_ownership` | Separate canonical memory from compiled context |
| `repository.command_output_is_not_source` | Treat command-output snapshots as historical evidence |

Every policy must include a unique ID, title, domain, positive priority,
rule, enforcement state and known limitation.

A documented policy must not be misrepresented as an automated security
or authorization control.

## 7. Foundation Integrity Gate

Before compilation the compiler must validate:

- Registry integrity.
- Canonical company and primary project identity.
- Exact eight-agent registry roster.
- Registry audit-chain integrity.
- Memory SQLite integrity.
- Registry-to-memory identity bindings.
- Foundation migration version.

When validation fails, compilation must stop without returning a partial
company context or modifying canonical records.

## 8. Context Scope

L0 includes company identity, primary project identity, specialist roster,
specification-readiness status, company policies, storage boundary and
validation evidence.

It explicitly excludes later context responsibilities:

| Level | Responsibility |
|---|---|
| L1 | Project requirements, goals, decisions, project memory and task backlog |
| L2 | One specialist's architecture, workflow, domain contracts and task ownership |
| L3 | Current task's relevant source files, symbols and dependencies |
| L4 | Deep audit evidence, security findings, test history and approvals |

L0 must disclose these boundaries and must not claim that it contains
complete project or specialist context.

## 9. Token Budget Contract

The compiler accepts a maximum context budget and reserved output budget.

`available_context_tokens = max_context_tokens - reserved_output_tokens`

The current deterministic estimate is:

`ceil(UTF-8 serialized bytes / 3)`

This is a heuristic, not an exact tokenizer for any model provider.

The packet must disclose maximum, reserved, available and estimated tokens,
estimation method, truncation state and omitted sections.

Required identity, roster and company policies must never be silently
truncated. Budget overflow must fail compilation.

## 10. Context Integrity

The policy catalog and compiled context must have deterministic SHA-256
digests.

Serialization must use UTF-8, sorted keys, stable ordering, consistent
separators and finite JSON values.

The packet digest excludes its own `packet_sha256` field.

A digest detects changes relative to the supplied packet; it is not an
external digital signature or proof of tamper-proof storage.

## 11. Memory Read-Only Contract

L0 compilation must not insert or update memories, tasks, checkpoints,
registry records or events.

A compilation operation must not append a memory event.

## 12. Output Safety

The L0 writer must reject an unsupported schema, missing digest or modified
packet. The CLI must reject output paths outside the repository root and
must write through a temporary file and atomic replacement.

Default output:

`.ai-dev-company/context/l0-company-context.json`

This runtime artifact must not be committed as ordinary source.

## 13. Execution Command

After Foundation initialization:

```bash
python -m company_os.context.l0_cli --root .
