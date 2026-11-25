
### 11. NEW FILE — `company_os/context/SPECIALIST_CONTEXT_ACCEPTANCE.md`

```markdown
# Specialist Context — L2 Acceptance Contract

**Context level:** L2  
**Implementation:** `company_os/context/specialist_context.py`  
**CLI:** `company_os/context/l2_cli.py`  
**Loader:** `ai_dev_company/agent_loader.py`  
**Specification source:** `agents/<specialist-slug>/agent.yaml`  
**Automated tests:** `tests/test_specialist_context.py`

## 1. Purpose

L2 compiles one specialist's validated domain specification over the
authoritative L1 project context.

It must never combine the ownership or operating policies of multiple
specialists into one generic role.

## 2. Identity and specification validation

The requested specialist must be one of the canonical eight slugs.

The manifest must match the live registry identity, domain, role version
and exact canonical capability list.

Required manifest sections include:

- Identity and mission.
- Ownership and non-ownership.
- Inputs and outputs.
- Architecture components, data objects and invariants.
- Workflow stages and stop conditions.
- Tool policy and privileged-action approval requirements.
- Quality gates.
- Memory policy.
- Failure modes and escalation routes.
- Evaluation scenarios.
- Handoff contracts.
- Explicit readiness state.

Missing or invalid specifications must stop compilation.

## 3. Task ownership

When a task ID is requested:

- The task must exist in the canonical L1 backlog.
- It must be assigned to the requested specialist or remain unassigned.
- A task assigned to another specialist must be rejected.
- Every direct dependency must resolve to a task in the same L1 snapshot.
- The selected task and direct dependencies must be included in the context.

Without a task ID, L2 may include only tasks assigned to the selected specialist.

L2 does not change task status or execute the task.

## 4. Permission boundary

A manifest describes candidate capabilities; it does not grant tools.

The compiled packet must explicitly report that tool access is not granted
by the context compiler.

Authorization, approval, sandboxing and tool execution remain responsibilities
of the future shared runtime.

## 5. Integrity and budgeting

L2 includes a validated L1 parent, specialist manifest, registry identity,
task scope, handoff contracts and provenance.

The packet must include a deterministic SHA-256 digest and token budget.

No required specialist contract or parent context may be silently truncated.

The writer must reject modified packets and write atomically.

## 6. Non-execution guarantee

L2 compilation must not:

- Call an AI provider.
- Execute a specialist.
- Execute tools.
- Grant privileged access.
- Change tasks or memory.
- Activate a registered agent.

Specification readiness is not runtime readiness or activation.

## 7. Required regression scenarios

- All eight manifests match the canonical registry.
- Every specialist has a distinct domain and mission.
- L2 includes the selected specialist and the validated L1 parent.
- Task scope contains only the selected specialist's assigned work.
- Cross-specialist task requests are refused.
- Missing and malformed specifications are refused.
- Memory remains unchanged during compilation.
- Packet digests reject post-compilation modification.
- Token budget and output-path validation fail safely.

## 8. Execution command

```bash
python -m company_os.context.l2_cli --root . --agent backend-developer
