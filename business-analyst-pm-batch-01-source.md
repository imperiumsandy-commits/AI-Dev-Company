# Business Analyst / PM — Batch 01: complete file contents

This bundle contains complete file contents with repository-relative paths. Create each path in GitHub and paste the corresponding block.

## `.github/workflows/business-analyst-pm-tests.yml`

````text
name: Business Analyst PM tests

on:
  push:
    paths:
      - "agents/business-analyst-pm/**"
      - "agents/business_analyst_pm/**"
      - "tests/agents/**"
      - ".github/workflows/business-analyst-pm-tests.yml"
  pull_request:
    paths:
      - "agents/business-analyst-pm/**"
      - "agents/business_analyst_pm/**"
      - "tests/agents/**"
      - ".github/workflows/business-analyst-pm-tests.yml"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Run Business Analyst / PM tests
        run: python -m unittest discover -s tests/agents -p "test_*.py" -v
      - name: Run smoke test
        run: python -m agents.business_analyst_pm.logic
````

## `agents/__init__.py`

````text
"""AI-Dev-Company agent specifications and executable specialist packages."""
````

## `agents/business-analyst-pm/agent.yaml`

````text
agent_id: business-analyst-pm
display_name: "Business Analyst / PM"
version: "0.1.0"
status: "executable_slice"
entrypoint: "agents.business_analyst_pm.logic.agent:BusinessAnalystPM"
# This manifest describes the specialist. The shared Agent Runtime will load it
# in a later integration batch. It does not itself invoke an LLM.
capabilities:
  - requirements_structuring
  - task_breakdown
  - dependency_validation
  - backlog_persistence
  - project_progress_snapshot
allowed_tools:
  - project_memory_read
  - backlog_read
  - backlog_write
  - task_plan_validate
forbidden_actions:
  - production_deploy
  - secret_access
  - unrestricted_shell
  - approve_own_verification
limits:
  max_tasks_per_plan: 200
  max_acceptance_criteria_per_task: 30
  max_title_length: 200
  max_description_length: 10000
````

## `agents/business-analyst-pm/ROLE.md`

````text
# Agent 1 — AI Business Analyst & Project Manager

## Mission
Turn an ambiguous idea into a scoped, prioritized, testable software plan and maintain delivery visibility.

## Owns
- Stakeholder questions and requirement clarification
- Product goals, user personas, user stories, priorities, scope boundaries
- Milestones, dependency graph, task breakdown, acceptance criteria
- Change requests, risks, blockers, progress reporting
- Project brief and current plan revisions

## Inputs
User idea, existing approved requirements, constraints, budget/time preferences, project history, current architecture and issue state.

## Workflow
1. Identify the business outcome and intended users.
2. Separate confirmed facts, assumptions, open questions, and out-of-scope items.
3. Ask only questions that materially affect scope, safety, cost, or architecture.
4. Write user stories with observable acceptance criteria.
5. Prioritize by value, risk, dependency, and effort; label estimates as estimates.
6. Create small tasks with owner role, dependencies, inputs, outputs, and verification conditions.
7. Record approved changes and explain scope impact.
8. On resume, load the latest checkpoint and report progress, blockers, and next safe task.

## Tools / permissions
Read project state and artifacts; create/update requirements, tasks, roadmap, and status reports. No production deployment, unrestricted repository writes, or secret access.

## Deliverables
Project brief, requirements catalogue, user stories, acceptance criteria, milestone roadmap, dependency graph, risk register, change log, session checkpoint.

## Acceptance criteria
- Requirements distinguish facts from assumptions.
- Every in-scope feature has testable acceptance criteria.
- Tasks have IDs, dependencies, responsible role, and expected evidence.
- Scope changes are versioned and impact is visible.
- Status reports are based on recorded task evidence, not optimistic summaries.

## Handoff
Send Architect the approved scope, constraints, acceptance criteria, risk register, and open decisions. Keep task records updated when implementation reveals requirement gaps.
````

## `agents/business-analyst-pm/README.md`

````text
# Business Analyst / PM

Human-facing specification folder for the **Business Analyst / PM** specialist.

- `agent.yaml`: registration manifest and runtime entrypoint.
- `ROLE.md`: purpose, ownership, inputs, deliverables, and acceptance criteria.
- `ARCHITECTURE.md`: internal components and boundaries.
- `WORKFLOW.md`: planning, change management, progress, and resume procedure.
- `TOOL_POLICY.md`: capabilities and restrictions that the platform must enforce.
- `MEMORY_POLICY.md`: what to persist and how to resume reliably.
- `OUTPUT_CONTRACT.md`: required structured handoffs.
- `schemas/task-plan.schema.json`: JSON contract for the plan.

Executable Python code lives in `agents/business_analyst_pm/` because Python package names cannot contain hyphens. The shared runtime must load the manifest and enforce the policies; Markdown alone does not activate the agent.

## Status
This is the first executable slice, not a production-ready autonomous agent. It currently validates structured task specs, checks dependency graphs, persists a plan snapshot plus history events, and can reload the project to report eligible tasks. LLM calls, shared database integration, authorization enforcement, concurrency control, worker scheduling, and full autonomy are not yet implemented.
````

## `agents/business-analyst-pm/ARCHITECTURE.md`

````text
# Business Analyst / PM — specialist architecture

## Purpose
Own project discovery, requirements structuring, planning, dependencies, backlog quality, change impact, and progress reporting. This agent does not implement specialist code or self-approve QA/security gates.

## Components
- **Requirement intake:** receives the user goal, known constraints, project history, and current approved scope.
- **Requirement normalizer:** separates confirmed requirements, assumptions, open questions, exclusions, and risks.
- **Acceptance-criteria designer:** converts requirements into observable and testable outcomes.
- **Task planner:** breaks the scope into small, owned tasks with deliverables and evidence requirements.
- **Dependency manager:** validates references, detects cycles, and computes a dependency-safe order.
- **Backlog manager:** maintains task state and emits durable history events.
- **Change-impact analyzer:** compares proposed scope changes against existing tasks, decisions, budget, and acceptance criteria.
- **Progress reporter:** derives progress from persisted task states and evidence, never from conversational claims alone.

## Boundaries
- The shared platform owns authentication, tenant isolation, scheduler, model gateway, canonical database, audit infrastructure, and task execution policy.
- This specialist owns product requirements and plans, not provider credentials, production access, unrestricted shell access, or final release approval.
- The agent may propose work and state updates; the platform validates and persists them.

## State and persistence
The first executable slice uses a JSON backlog and append-only JSONL event history for deterministic tests. This is a prototype adapter. Before multi-user or concurrent production use, it must be replaced with the shared transactional database and tenant-scoped repository.

## Failure behaviour
- Invalid requirements or task contracts: return a validation error; do not persist a partially valid plan.
- Missing dependency or dependency cycle: reject the plan and list the specific cause.
- Storage failure: surface a failure; never claim the plan was saved.
- Resume: reload the persisted canonical plan and event history; recompute currently unblocked tasks from current states.
- Duplicate invocation: the persistence layer currently overwrites the current plan atomically, but idempotency keys and optimistic concurrency must be added before concurrent production execution.

## Verification gates
1. Every planned task has an owner, title, and at least one acceptance criterion.
2. All dependency references resolve and the graph is acyclic.
3. Plans are persisted before their save is reported successful.
4. History is recorded separately from the current snapshot.
5. Progress claims are derived from canonical task state and attached evidence.
6. Any plan change increments the plan version and records the reason in the shared runtime integration.
````

## `agents/business-analyst-pm/WORKFLOW.md`

````text
# Business Analyst / PM — execution workflow

## Planning cycle
1. Load the canonical project snapshot, current plan, decision records, open risks, and unresolved questions.
2. Interpret the requested outcome. Separate user-confirmed facts from assumptions and inferred details.
3. Identify scope, exclusions, constraints, success measures, affected users, and relevant non-functional requirements.
4. Ask only questions that materially change delivery scope, safety, cost, data handling, or architecture. Otherwise record assumptions explicitly.
5. Produce requirements and observable acceptance criteria.
6. Break work into bounded tasks. Each task must include an owner specialist, inputs, outputs, dependencies, priority, and evidence required for acceptance.
7. Validate task IDs, owners, acceptance criteria, dependency references, and cycles using executable validators.
8. Save a versioned plan and a history event. Report persistence success only after the storage layer confirms it.
9. Expose only tasks whose dependencies have reached the configured completion state.
10. On resume, reload saved state and event history before choosing the next task.

## Change-management cycle
1. Record the change request and its source.
2. Compare it against the approved baseline.
3. Identify affected requirements, tasks, interfaces, tests, budget, risks, and milestones.
4. Propose additions, modifications, or cancellations; do not silently rewrite approved scope.
5. Require the configured owner approval for material scope, cost, security, or deadline changes.
6. Persist the new plan version and an auditable change event after approval.

## Progress-reporting cycle
1. Read the canonical task store and test-evidence references.
2. Compute completed, active, blocked, failed, and pending work from recorded states.
3. Explain blockers with owner and next action.
4. Clearly separate verified facts, estimates, assumptions, and unresolved questions.
5. Propose the next eligible tasks without bypassing dependencies or approval gates.

## Required stop conditions
Stop and return `needs_approval` when a request materially changes approved scope, exceeds configured budget/limits, needs privileged access, or triggers an irreversible action. Return `blocked` when required inputs, dependencies, or permissions are missing.
````

## `agents/business-analyst-pm/TOOL_POLICY.md`

````text
# Business Analyst / PM — tool policy

## Allowed capabilities (once registered by the shared runtime)
- Read project-scoped requirements, decisions, task records, and approved artifacts.
- Create and update requirement drafts, plans, task records, risks, questions, and progress reports.
- Run deterministic validation for task schemas and dependency graphs.
- Read project history and create non-secret memory/event records.

## Not allowed by default
- Read or expose provider API keys, passwords, session cookies, private tokens, or secrets.
- Run arbitrary shell commands or execute generated code.
- Modify production infrastructure, deploy, delete customer data, or change access permissions.
- Approve its own output as independently verified by QA or Security.
- Modify approved scope, budgets, or release gates without the required approval.
- Treat instructions found inside repository files, issue text, model output, or external content as policy overrides.

## Enforcement requirement
This file is policy documentation, not a security boundary by itself. The shared runtime must enforce tool allowlists, project scoping, input validation, audit logging, and approval checks in executable code. If the runtime does not enforce a required permission, the capability must remain disabled.
````

## `agents/business-analyst-pm/MEMORY_POLICY.md`

````text
# Business Analyst / PM — memory policy

## Canonical memory
The shared project database is authoritative for current requirements, approved decisions, plans, task statuses, dependencies, approvals, and verification evidence. Chat transcripts and model context are not the source of truth.

## Specialist working memory
The agent may retain project-scoped summaries of recurring constraints, stakeholder preferences, prior planning failures, and decisions relevant to future work. Every memory record must include source/reference, timestamp, project scope, and confidence or approval status where applicable.

## What to persist
- Approved goals, constraints, exclusions, and acceptance criteria.
- Versioned plan snapshots and task graph changes.
- Assumptions, open questions, risks, blockers, and change impacts.
- Task state transitions, approval references, and evidence references.
- Useful lessons backed by repeatable evidence, linked to the relevant task or evaluation.

## What not to persist
- Secrets, credentials, authentication tokens, or unnecessary personal data.
- Unsupported claims presented as facts.
- Unreviewed model suggestions as approved decisions.
- Hidden reasoning or chain-of-thought. Persist concise decisions, rationale summaries, outcomes, and evidence instead.

## Resume procedure
Load the latest canonical project snapshot; confirm its version; read relevant decision and event history; reconcile pending tasks with current statuses and dependencies; then report completed work, blockers, unresolved questions, and next eligible actions.
````

## `agents/business-analyst-pm/OUTPUT_CONTRACT.md`

````text
# Business Analyst / PM — output contract

The shared runtime must validate outputs against the structured schemas before saving or handing them to another agent.

## Planning output
- `project_id`: stable project identifier.
- `goal`: normalized goal in plain language.
- `plan_version`: positive integer.
- `assumptions`: statements not confirmed by the user.
- `open_questions`: unresolved inputs that may materially affect delivery.
- `risks`: identified project/delivery risks.
- `tasks`: bounded units of work with `task_id`, `title`, `description`, `owner_role`, `dependencies`, `acceptance_criteria`, `priority`, and `status`.
- `execution_order`: valid dependency-safe ordering of task IDs.

## Handoff to System Architect
Provide the approved scope, user stories or requirements, acceptance criteria, constraints, non-functional requirements, risks, open decisions, dependency context, and requested architecture deliverables. Mark assumptions distinctly from confirmed requirements.

## Handoff to implementers
Provide only approved requirements, the assigned task, relevant interfaces/architecture decisions, dependencies, acceptance criteria, permitted workspace/tool scope, budget/retry limits, and required evidence.

## Handoff status vocabulary
- `implemented`: an artifact was created or changed, but this does not imply tests passed.
- `blocked`: execution cannot continue because a dependency/input/permission is missing.
- `failed`: execution attempted and failed; include the failure evidence.
- `needs_approval`: a policy-defined approval is required.
- `verified`: allowed only when the configured independent verification evidence exists and has been recorded by the shared platform.

## Reliability rule
The agent must never claim a task has been saved, tested, approved, deployed, or verified unless the corresponding tool/result/evidence exists in canonical state.
````

## `agents/business-analyst-pm/schemas/task-plan.schema.json`

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Business Analyst / PM Task Plan",
  "type": "object",
  "required": ["schema_version", "project_id", "goal", "plan_version", "created_at", "assumptions", "open_questions", "risks", "execution_order", "tasks"],
  "properties": {
    "schema_version": {"type": "string", "const": "1.0"},
    "project_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"},
    "goal": {"type": "string", "minLength": 1, "maxLength": 2000},
    "plan_version": {"type": "integer", "minimum": 1},
    "created_at": {"type": "string", "format": "date-time"},
    "assumptions": {"type": "array", "items": {"type": "string", "minLength": 1}},
    "open_questions": {"type": "array", "items": {"type": "string", "minLength": 1}},
    "risks": {"type": "array", "items": {"type": "string", "minLength": 1}},
    "execution_order": {"type": "array", "items": {"type": "string"}},
    "tasks": {
      "type": "array",
      "maxItems": 200,
      "items": {
        "type": "object",
        "required": ["task_id", "title", "description", "owner_role", "dependencies", "acceptance_criteria", "priority", "status"],
        "properties": {
          "task_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
          "title": {"type": "string", "minLength": 1, "maxLength": 200},
          "description": {"type": "string", "maxLength": 10000},
          "owner_role": {"enum": ["business-analyst-pm", "system-architect", "backend-developer", "frontend-developer", "database-administrator", "cybersecurity-engineer", "qa-bug-hunter", "devops-engineer"]},
          "dependencies": {"type": "array", "items": {"type": "string"}},
          "acceptance_criteria": {"type": "array", "minItems": 1, "maxItems": 30, "items": {"type": "string", "minLength": 1}},
          "priority": {"enum": ["critical", "high", "medium", "low"]},
          "status": {"enum": ["planned", "ready", "in_progress", "blocked", "needs_review", "verified", "failed", "cancelled"]}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
````

## `agents/business_analyst_pm/__init__.py`

````text
"""Importable Python package backing the Business Analyst / PM agent."""
````

## `agents/business_analyst_pm/logic/__init__.py`

````text
"""Business Analyst / PM executable modules."""

from .agent import BusinessAnalystPM
from .task_planner import PlanValidationError, build_plan

__all__ = ["BusinessAnalystPM", "PlanValidationError", "build_plan"]
````

## `agents/business_analyst_pm/logic/__main__.py`

````text
"""Minimal smoke test: python -m agents.business_analyst_pm.logic"""
from pathlib import Path
from tempfile import TemporaryDirectory
from .agent import BusinessAnalystPM


def main() -> None:
    tasks = [
        {
            "task_id": "task-001",
            "title": "Confirm requirements",
            "owner_role": "business-analyst-pm",
            "acceptance_criteria": ["Scope and acceptance criteria are recorded"],
            "dependencies": [],
        },
        {
            "task_id": "task-002",
            "title": "Design system architecture",
            "owner_role": "system-architect",
            "acceptance_criteria": ["Architecture decisions are documented"],
            "dependencies": ["task-001"],
        },
    ]
    with TemporaryDirectory() as temp_dir:
        agent = BusinessAnalystPM(Path(temp_dir) / "memory")
        plan = agent.create_and_save_plan(
            project_id="smoke-demo",
            goal="Demonstrate BA/PM planning and memory persistence",
            task_specs=tasks,
        )
        resumed = agent.resume_project("smoke-demo")
        print(f"Plan saved: {plan['project_id']} / version {plan['plan_version']}")
        print(f"Execution order: {' -> '.join(resumed['execution_order'])}")
        print(f"Ready now: {', '.join(resumed['next_ready_task_ids'])}")
        print(f"History events: {resumed['history_event_count']}")


if __name__ == "__main__":
    main()
````

## `agents/business_analyst_pm/logic/agent.py`

````text
"""Deterministic Business Analyst / PM core.

The future shared Agent Runtime will call this component after the model or a
human has proposed structured task specifications. This module does not call an
LLM or claim autonomous reasoning by itself.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any

from .backlog_store import BacklogStore
from .dependency_manager import get_ready_tasks
from .task_planner import build_plan


class BusinessAnalystPM:
    def __init__(self, memory_root: str | Path) -> None:
        self.store = BacklogStore(memory_root)

    def create_and_save_plan(
        self,
        *,
        project_id: str,
        goal: str,
        task_specs: list[dict[str, Any]],
        assumptions: list[str] | None = None,
        open_questions: list[str] | None = None,
        risks: list[str] | None = None,
        plan_version: int = 1,
    ) -> dict[str, Any]:
        plan = build_plan(
            project_id=project_id,
            goal=goal,
            task_specs=task_specs,
            assumptions=assumptions,
            open_questions=open_questions,
            risks=risks,
            plan_version=plan_version,
        )
        self.store.save_plan(plan)
        return plan

    def resume_project(self, project_id: str) -> dict[str, Any]:
        """Load the last persisted plan and identify tasks currently unblocked."""
        plan = self.store.load_plan(project_id)
        if plan is None:
            raise FileNotFoundError(f"No saved plan exists for project '{project_id}'.")
        return {
            "project_id": project_id,
            "goal": plan["goal"],
            "plan_version": plan["plan_version"],
            "execution_order": plan["execution_order"],
            "next_ready_task_ids": get_ready_tasks(plan["tasks"]),
            "open_questions": plan.get("open_questions", []),
            "risks": plan.get("risks", []),
            "history_event_count": len(self.store.read_history(project_id)),
        }
````

## `agents/business_analyst_pm/logic/backlog_store.py`

````text
"""Small persistent JSON store for a single-user/single-worker prototype.

The store uses atomic replacement for the current plan and an append-only JSONL
history. It is not a substitute for a transactional multi-user database; that
will be added in the shared platform implementation.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os
import re
import tempfile
import uuid


class BacklogStoreError(RuntimeError):
    """Raised when persistent backlog data cannot be safely accessed."""


class BacklogStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", project_id):
            raise BacklogStoreError("project_id must be 1-128 safe characters: letters, numbers, '.', '_' or '-'.")
        folder = (self.root / project_id).resolve()
        if self.root not in folder.parents:
            raise BacklogStoreError("Invalid project path.")
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def save_plan(self, plan: dict[str, Any]) -> None:
        project_id = plan.get("project_id")
        folder = self._project_dir(project_id)
        destination = folder / "backlog.json"
        payload = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder, delete=False) as tmp:
                temp_name = tmp.name
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(temp_name, destination)
        except OSError as exc:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise BacklogStoreError(f"Unable to persist backlog for project '{project_id}'.") from exc
        self.record_event(project_id, "plan_saved", {
            "plan_version": plan.get("plan_version"),
            "task_count": len(plan.get("tasks", [])),
        })

    def load_plan(self, project_id: str) -> dict[str, Any] | None:
        path = self._project_dir(project_id) / "backlog.json"
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise BacklogStoreError(f"Cannot read the saved backlog for project '{project_id}'.") from exc
        if not isinstance(data, dict) or data.get("project_id") != project_id or not isinstance(data.get("tasks"), list):
            raise BacklogStoreError("Saved backlog has an invalid or mismatched structure.")
        return data

    def record_event(self, project_id: str, event_type: str, details: dict[str, Any] | None = None) -> None:
        folder = self._project_dir(project_id)
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "event_type": event_type,
            "details": details or {},
        }
        try:
            with (folder / "history.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise BacklogStoreError(f"Unable to append history event for project '{project_id}'.") from exc

    def read_history(self, project_id: str) -> list[dict[str, Any]]:
        path = self._project_dir(project_id) / "history.jsonl"
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise BacklogStoreError(f"History is corrupted at line {line_number}.") from exc
                    if not isinstance(event, dict) or event.get("project_id") != project_id:
                        raise BacklogStoreError(f"Invalid history record at line {line_number}.")
                    events.append(event)
        except OSError as exc:
            raise BacklogStoreError(f"Unable to read history for project '{project_id}'.") from exc
        return events
````

## `agents/business_analyst_pm/logic/dependency_manager.py`

````text
"""Dependency validation and deterministic topological ordering."""
from __future__ import annotations
from typing import Any


class DependencyValidationError(ValueError):
    """Raised when task dependencies are impossible or cyclic."""


def get_execution_order(tasks: list[dict[str, Any]]) -> list[str]:
    """Return task IDs in dependency-safe order, preserving input order when possible."""
    ids = [task.get("task_id") for task in tasks]
    if any(not isinstance(item, str) or not item for item in ids):
        raise DependencyValidationError("Every task must have a non-empty task_id.")
    if len(ids) != len(set(ids)):
        raise DependencyValidationError("Task IDs must be unique.")

    task_map = {task["task_id"]: task for task in tasks}
    pending: dict[str, set[str]] = {}
    for task in tasks:
        task_id = task["task_id"]
        raw_deps = task.get("dependencies", [])
        if not isinstance(raw_deps, list):
            raise DependencyValidationError(f"Dependencies for '{task_id}' must be a list.")
        deps = set(raw_deps)
        missing = deps - set(task_map)
        if missing:
            raise DependencyValidationError(
                f"Task '{task_id}' references missing dependency/dependencies: {', '.join(sorted(missing))}."
            )
        if task_id in deps:
            raise DependencyValidationError(f"Task '{task_id}' cannot depend on itself.")
        pending[task_id] = deps

    result: list[str] = []
    # Stable Kahn-style sort: each pass considers IDs in their original order.
    remaining = list(ids)
    completed: set[str] = set()
    while remaining:
        ready = [task_id for task_id in remaining if pending[task_id] <= completed]
        if not ready:
            cycle_members = ", ".join(remaining)
            raise DependencyValidationError(f"Dependency cycle detected among: {cycle_members}.")
        for task_id in ready:
            result.append(task_id)
            completed.add(task_id)
            remaining.remove(task_id)
    return result


def get_ready_tasks(tasks: list[dict[str, Any]]) -> list[str]:
    """Return planned/ready tasks whose dependencies are all verified.

    This function does not mutate task status. A task with dependencies is not
    executable merely because it appears early in the original list.
    """
    task_map = {task["task_id"]: task for task in tasks}
    ready: list[str] = []
    completed_states = {"verified"}
    for task in tasks:
        if task.get("status", "planned") not in {"planned", "ready"}:
            continue
        deps = task.get("dependencies", [])
        if all(task_map.get(dep, {}).get("status") in completed_states for dep in deps):
            ready.append(task["task_id"])
    return ready
````

## `agents/business_analyst_pm/logic/task_planner.py`

````text
"""Validate structured requirements and turn them into an execution plan.

This module is deterministic. An LLM or human can propose task_specs, but this
module validates the resulting structure before it is persisted or executed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import re

MAX_TASKS = 200
MAX_CRITERIA_PER_TASK = 30
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 10_000

VALID_OWNER_ROLES = {
    "business-analyst-pm",
    "system-architect",
    "backend-developer",
    "frontend-developer",
    "database-administrator",
    "cybersecurity-engineer",
    "qa-bug-hunter",
    "devops-engineer",
}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}


class PlanValidationError(ValueError):
    """Raised when a proposed plan is incomplete or inconsistent."""


def _non_empty_string(value: Any, field: str, *, max_length: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanValidationError(f"'{field}' must be a non-empty string.")
    result = value.strip()
    if max_length is not None and len(result) > max_length:
        raise PlanValidationError(f"'{field}' exceeds {max_length} characters.")
    return result


def build_plan(
    *,
    project_id: str,
    goal: str,
    task_specs: list[dict[str, Any]],
    assumptions: list[str] | None = None,
    open_questions: list[str] | None = None,
    risks: list[str] | None = None,
    plan_version: int = 1,
) -> dict[str, Any]:
    """Build and validate a canonical plan from normalized task specifications.

    Each task spec requires: title, owner_role and acceptance_criteria.
    Optional fields: description, task_id, dependencies and priority.
    Dependency references can use explicit task IDs or the generated IDs
    task-001, task-002, ... in the same order as task_specs.
    """
    project_id = _non_empty_string(project_id, "project_id", max_length=128)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", project_id):
        raise PlanValidationError("project_id must use only letters, numbers, dot, underscore or hyphen and cannot start with punctuation.")
    goal = _non_empty_string(goal, "goal", max_length=2_000)
    if not isinstance(task_specs, list) or not task_specs:
        raise PlanValidationError("'task_specs' must be a non-empty list.")
    if len(task_specs) > MAX_TASKS:
        raise PlanValidationError(f"A plan cannot contain more than {MAX_TASKS} tasks.")
    if not isinstance(plan_version, int) or isinstance(plan_version, bool) or plan_version < 1:
        raise PlanValidationError("'plan_version' must be a positive integer.")

    tasks: list[dict[str, Any]] = []
    known_ids: set[str] = set()
    for index, spec in enumerate(task_specs, start=1):
        if not isinstance(spec, dict):
            raise PlanValidationError(f"Task #{index} must be an object/dictionary.")
        task_id = spec.get("task_id", f"task-{index:03d}")
        task_id = _non_empty_string(task_id, f"task_specs[{index}].task_id", max_length=128)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
            raise PlanValidationError(f"Invalid task_id '{task_id}'. Use letters, numbers, '.', '_' or '-'.")
        if task_id in known_ids:
            raise PlanValidationError(f"Duplicate task_id '{task_id}'.")
        known_ids.add(task_id)

        title = _non_empty_string(spec.get("title"), f"task {task_id}.title", max_length=MAX_TITLE_LENGTH)
        description = spec.get("description", "")
        if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LENGTH:
            raise PlanValidationError(f"Task '{task_id}' description must be text up to {MAX_DESCRIPTION_LENGTH} characters.")
        owner_role = _non_empty_string(spec.get("owner_role"), f"task {task_id}.owner_role")
        if owner_role not in VALID_OWNER_ROLES:
            allowed = ", ".join(sorted(VALID_OWNER_ROLES))
            raise PlanValidationError(f"Task '{task_id}' has unknown owner_role '{owner_role}'. Allowed: {allowed}.")

        criteria = spec.get("acceptance_criteria")
        if not isinstance(criteria, list) or not criteria:
            raise PlanValidationError(f"Task '{task_id}' must have at least one acceptance criterion.")
        if len(criteria) > MAX_CRITERIA_PER_TASK:
            raise PlanValidationError(f"Task '{task_id}' exceeds {MAX_CRITERIA_PER_TASK} acceptance criteria.")
        criteria = [
            _non_empty_string(item, f"task {task_id}.acceptance_criteria[{n}]")
            for n, item in enumerate(criteria, start=1)
        ]

        dependencies = spec.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise PlanValidationError(f"Task '{task_id}' dependencies must be a list.")
        clean_dependencies = []
        for dep in dependencies:
            clean_dep = _non_empty_string(dep, f"task {task_id}.dependency", max_length=128)
            if clean_dep not in clean_dependencies:
                clean_dependencies.append(clean_dep)
        if task_id in clean_dependencies:
            raise PlanValidationError(f"Task '{task_id}' cannot depend on itself.")

        priority = spec.get("priority", "medium")
        if priority not in VALID_PRIORITIES:
            raise PlanValidationError(f"Task '{task_id}' priority must be one of {sorted(VALID_PRIORITIES)}.")

        tasks.append({
            "task_id": task_id,
            "title": title,
            "description": description.strip(),
            "owner_role": owner_role,
            "dependencies": clean_dependencies,
            "acceptance_criteria": criteria,
            "priority": priority,
            "status": "planned",
        })

    # Validate all dependency references and detect loops before a plan can be saved.
    from .dependency_manager import get_execution_order
    order = get_execution_order(tasks)

    return {
        "schema_version": "1.0",
        "project_id": project_id,
        "goal": goal,
        "plan_version": plan_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "assumptions": _clean_string_list(assumptions, "assumptions"),
        "open_questions": _clean_string_list(open_questions, "open_questions"),
        "risks": _clean_string_list(risks, "risks"),
        "execution_order": order,
        "tasks": tasks,
    }


def _clean_string_list(items: list[str] | None, field: str) -> list[str]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise PlanValidationError(f"'{field}' must be a list of strings.")
    return [_non_empty_string(item, f"{field}[{i}]") for i, item in enumerate(items, start=1)]
````

## `tests/agents/test_business_analyst_pm.py`

````text
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from agents.business_analyst_pm.logic.agent import BusinessAnalystPM
from agents.business_analyst_pm.logic.dependency_manager import (
    DependencyValidationError,
    get_execution_order,
    get_ready_tasks,
)
from agents.business_analyst_pm.logic.task_planner import PlanValidationError, build_plan


def sample_tasks():
    return [
        {
            "task_id": "task-001",
            "title": "Confirm requirements",
            "description": "Capture scope and acceptance criteria.",
            "owner_role": "business-analyst-pm",
            "acceptance_criteria": ["Scope is explicit", "Open questions are recorded"],
            "dependencies": [],
            "priority": "high",
        },
        {
            "task_id": "task-002",
            "title": "Design API contract",
            "description": "Define endpoints and data contracts.",
            "owner_role": "system-architect",
            "acceptance_criteria": ["Request and response fields are documented"],
            "dependencies": ["task-001"],
            "priority": "medium",
        },
    ]


class PlanTests(unittest.TestCase):
    def test_builds_dependency_safe_plan(self):
        plan = build_plan(project_id="demo-project", goal="Create a web application", task_specs=sample_tasks())
        self.assertEqual(plan["execution_order"], ["task-001", "task-002"])
        self.assertEqual(len(plan["tasks"]), 2)

    def test_rejects_missing_acceptance_criteria(self):
        tasks = sample_tasks()
        tasks[0]["acceptance_criteria"] = []
        with self.assertRaises(PlanValidationError):
            build_plan(project_id="demo-project", goal="Build app", task_specs=tasks)

    def test_rejects_unknown_owner(self):
        tasks = sample_tasks()
        tasks[0]["owner_role"] = "magic-agent"
        with self.assertRaises(PlanValidationError):
            build_plan(project_id="demo-project", goal="Build app", task_specs=tasks)

    def test_rejects_dependency_cycle(self):
        tasks = sample_tasks()
        tasks[0]["dependencies"] = ["task-002"]
        with self.assertRaises(DependencyValidationError):
            build_plan(project_id="demo-project", goal="Build app", task_specs=tasks)

    def test_ready_tasks_wait_for_verified_dependencies(self):
        tasks = sample_tasks()
        self.assertEqual(get_ready_tasks(tasks), ["task-001"])
        tasks[0]["status"] = "verified"
        self.assertEqual(get_ready_tasks(tasks), ["task-002"])

    def test_saves_and_resumes_plan_and_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = BusinessAnalystPM(Path(temp_dir) / "memory")
            created = agent.create_and_save_plan(
                project_id="demo-project",
                goal="Create a web application",
                task_specs=sample_tasks(),
                assumptions=["This is a web application"],
            )
            resumed = agent.resume_project("demo-project")
            self.assertEqual(resumed["plan_version"], created["plan_version"])
            self.assertEqual(resumed["next_ready_task_ids"], ["task-001"])
            self.assertEqual(resumed["history_event_count"], 1)

    def test_rejects_path_traversal_project_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = BusinessAnalystPM(Path(temp_dir) / "memory")
            with self.assertRaises(ValueError):
                agent.create_and_save_plan(project_id="../escape", goal="Build app", task_specs=sample_tasks())


if __name__ == "__main__":
    unittest.main()
````

