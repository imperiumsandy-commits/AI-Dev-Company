# L0 Company Context — Acceptance Contract

**Component:** AI-Dev-Company Company OS  
**Context level:** L0 — Company Identity and Operating Policies  
**Contract version:** 1.0  
**Implementation module:** `company_os/context/l0_company_context.py`  
**Policy catalog:** `company_os/context/company_policies.py`  
**Automated tests:** `tests/test_l0_company_context.py`

---

## 1. Purpose

L0 provides the minimum authoritative company context required by every
subsequent project or specialist context level.

L0 must establish:

1. Which company owns the system.
2. Which repository and primary project are authoritative.
3. Which eight specialist domains belong to the company.
4. Which company-wide operating policies must be respected.
5. Which capabilities are implemented and which remain unavailable.
6. Which source records establish the context's authority.

L0 is not a generic AI-agent prompt and is not a replacement for project
memory, specialist architecture, task history, or repository intelligence.

## 2. Authoritative Company Identity

The company identity must come from the validated Company Registry.

| Field | Required value |
|---|---|
| Company ID | `co_ai_dev_company` |
| Slug | `ai-dev-company` |
| Name | `AI Software Engineering Company` |
| Required status | `active` |

The compiler must not create, repair, or silently replace registry records.

The compiler must refuse to produce an L0 packet when the Foundation
validation result is invalid.

Owner contact information, including owner email, must not be included
in the public L0 context packet.

## 3. Authoritative Project Identity

The primary project must come from the Company Registry.

| Field | Required value |
|---|---|
| Project ID | `prj_ai_dev_company` |
| Company ID | `co_ai_dev_company` |
| Slug | `ai-dev-company` |
| Name | `AI-Dev-Company` |
| Repository | `https://github.com/imperiumsandy-commits/AI-Dev-Company` |
| Default branch | `main` |
| Required status | `active` |

Exactly one canonical primary project must be available.

A different repository, branch, or company binding must not be silently
substituted.

## 4. Canonical Specialist Roster

The registry must contain exactly these eight unique specialists:

| ID | Specialist | Domain |
|---|---|---|
| `agent_business_analyst_pm` | Business Analyst / PM | Requirements and project management |
| `agent_system_architect` | System Architect | Architecture and technical design |
| `agent_backend_developer` | Backend Developer | Backend engineering |
| `agent_frontend_developer` | Frontend Developer | Frontend engineering |
| `agent_database_administrator` | Database Administrator | Database engineering |
| `agent_cybersecurity_engineer` | Cybersecurity Engineer | Application security |
| `agent_qa_bug_hunter` | QA / Bug Hunter | Quality assurance |
| `agent_devops_engineer` | DevOps Engineer | Platform and delivery engineering |

Acceptance conditions:

- Exactly eight records must exist.
- Every specialist ID must be unique.
- Every specialist must match the canonical registry catalog.
- Missing or additional specialists must cause compilation to fail.
- Specialist lifecycle status must be reported from the registry.
- A registered specialist must never be described as an active executable
  agent solely because its registry record exists.

The L0 compiler does not activate specialists.

## 5. Specialist Specification Readiness

The compiler must use the existing agent specification loader.

It must report, for each specialist:

- Specialist ID.
- Repository-relative specification folder, when available.
- Specification readiness status.
- Loaded specification filenames.
- Missing required specification filenames.

The loader's required specification files are:

- `ROLE.md`
- `ARCHITECTURE.md`
- `WORKFLOW.md`

The compiler must distinguish:

| State | Meaning |
|---|---|
| `missing_specification` | No usable specification directory exists |
| `ready_to_load` | A matching directory with a role file can be read |
| Registered | Specialist identity exists in the Registry |
| Active | Lifecycle state recorded by the Registry |

These states are not interchangeable.

Missing specialist files must be disclosed rather than replaced with
invented generic instructions.

The absence of specialist specification files does not invalidate the
canonical company identity. It remains an explicit readiness limitation.

## 6. Company Operating Policies

The policy catalog must contain nine uniquely identified company policies.

| Policy ID | Required subject |
|---|---|
| `company.project_separation` | Keep independent company projects separate |
| `company.specialist_independence` | Preserve eight specialist domains |
| `engineering.evidence_before_completion` | Evidence before completion |
| `delivery.github_is_source_of_truth` | GitHub-first source delivery |
| `security.credential_boundary` | Keep credentials outside ordinary storage and context |
| `governance.high_risk_owner_approval` | Owner approval for high-risk operations |
| `truth.registration_is_not_activation` | Report registration and activation truthfully |
| `memory.context_ownership` | Separate canonical memory from compiled context |
| `repository.command_output_is_not_source` | Treat command-output snapshots as historical evidence |

Every policy must include:

- Stable unique ID.
- Non-empty title.
- Domain.
- Unique positive priority.
- Explicit rule.
- Enforcement state.
- Known implementation limitation.

The policy catalog must be validated before compilation.

A documented policy must not be misrepresented as an already automated
enforcement mechanism.

## 7. Foundation Integrity Gate

The compiler must call the existing Foundation validation service before
reading company context records.

The validation must cover the existing Foundation contract, including:

- Registry integrity.
- Canonical company identity.
- Canonical primary project identity.
- Canonical eight-specialist roster.
- Registry audit-chain verification.
- Memory SQLite integrity.
- Registry-to-memory identity bindings.
- Foundation migration version.

When the Foundation validation fails:

- Context compilation must stop.
- No partial packet may be returned.
- No missing company or project record may be fabricated.
- The failure reason must be exposed to the caller.

The L0 compiler must not modify registry or memory records to make
validation pass.

## 8. Context Scope

L0 includes only:

- Company identity.
- Primary project identity.
- Canonical specialist roster.
- Specialist specification-readiness summary.
- Company-wide operating policies.
- Current storage boundary.
- Validation results.
- Source authority information.

L0 explicitly excludes:

| Later level | Responsibility |
|---|---|
| L1 | Project requirements, goals, decisions, and project knowledge |
| L2 | Specialist architecture, role instructions, and domain contracts |
| L3 | Current task, relevant source files, symbols, and dependencies |
| L4 | Deep audit evidence, security findings, test history, and approvals |

L0 must disclose these scope boundaries.

It must not claim to contain complete project or specialist context.

## 9. Token Budget Contract

The compiler must accept:

- Maximum context token budget.
- Reserved output token budget.

The available context budget is:

`available_context_tokens = max_context_tokens - reserved_output_tokens`

Both values must be validated.

Reserved output capacity must be smaller than the total maximum.

The current implementation uses a deterministic serialized-byte estimate:

`ceil(UTF-8 serialized bytes / 3)`

This is a heuristic.

It is not an exact tokenizer count for GPT, Claude, Gemini, or another
model provider.

The packet must disclose:

- Maximum budget.
- Reserved output capacity.
- Available context capacity.
- Estimated context size.
- Estimation method.
- Truncation state.
- Omitted sections.

Provider-specific tokenization remains future work.

## 10. No Silent Truncation

Required L0 content must never be silently truncated.

If the complete packet exceeds the available context budget:

- Compilation must fail.
- A budget-specific error must be returned.
- Estimated and available token counts must be disclosed.
- No partial packet may be represented as a complete L0 packet.

Identity, canonical specialist roster, and company operating policies
must remain complete.

## 11. Context Integrity

The policy catalog must have a deterministic SHA-256 digest.

The compiled packet must also have a deterministic SHA-256 digest.

Serialization must be deterministic:

- UTF-8.
- Sorted object keys.
- Stable policy ordering.
- Consistent separators.
- No non-finite JSON numbers.

The digest must be calculated over the packet content excluding its own
`packet_sha256` field.

Any modification after compilation must cause digest verification to fail
before the packet is written through the supported writer.

A digest detects content changes relative to the supplied packet. It does
not establish an external digital signature or tamper-proof storage.

## 12. Memory Read-Only Contract

The L0 compiler is a read-only context component.

It must not:

- Insert project memories.
- Update or archive memories.
- Create task records.
- Change task statuses.
- Create checkpoints.
- Rewrite registry records.
- Add registry configuration.
- Modify company operating policies in persistent memory.

The compiler may read validated Registry and Foundation state.

A compilation operation must not append a memory event.

## 13. Output Safety

The L0 CLI must:

- Resolve relative paths from the selected repository root.
- Reject output paths outside that root.
- Reject invalid context schemas.
- Reject packets without valid integrity digests.
- Write complete JSON.
- Use a temporary file and atomic replacement.
- Avoid leaving partial temporary files after failure.

Default output:

`.ai-dev-company/context/l0-company-context.json`

This generated runtime artifact must not be committed as ordinary source
code or confused with the authoritative source files.

## 14. Automated Regression Test Mapping

The primary implementation tests are:

`tests/test_l0_company_context.py`

| Acceptance requirement | Regression test |
|---|---|
| Canonical company/project and eight specialists | `test_l0_contains_canonical_company_project_and_exact_eight_specialists` |
| Owner contact privacy | `test_l0_does_not_expose_owner_email_or_owner_contact_data` |
| Policy catalog validity | `test_policy_catalog_is_specific_ordered_and_discloses_enforcement_limits` |
| Specification readiness disclosure | `test_l0_reports_registry_registration_separately_from_specification_readiness` |
| Deterministic packet and digest | `test_l0_compilation_is_deterministic_and_has_a_digest` |
| Memory read-only behaviour | `test_l0_compilation_does_not_append_memory_events` |
| Invalid registry/audit rejection | `test_l0_refuses_to_compile_when_foundation_integrity_fails` |
| Unbootstrapped Foundation rejection | `test_l0_refuses_an_empty_unbootstrapped_registry` |
| No silent truncation | `test_l0_never_silently_truncates_required_identity_or_policies` |
| Invalid budget rejection | `test_l0_rejects_invalid_token_budget` |
| Valid JSON output | `test_l0_packet_writer_is_valid_json_and_replaces_atomically` |
| Invalid schema/digest rejection | `test_l0_writer_rejects_wrong_schema_or_missing_digest` |
| Modified digest rejection | `test_l0_writer_rejects_a_modified_packet_digest` |
| CLI packet generation | `test_l0_cli_writes_context_packet_inside_repository` |
| Output path restriction | `test_l0_cli_rejects_output_outside_repository` |

The complete repository regression suite must also pass.

## 15. Execution Command

After Foundation initialization:

```bash
python -m company_os.context.l0_cli --root .
