"""Integrity-gated L1 project context compilation.

L1 extends the canonical L0 company context with project-scoped knowledge
and the complete current task backlog. It is deliberately read-only.

This module does not call model providers, execute tasks, modify memory,
or claim that local SQLite is cloud-shared storage.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from ai_dev_company.memory_store import TASK_STATUSES
from company_os.foundation import FoundationService

from .l0_company_context import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_RESERVED_OUTPUT_TOKENS,
    ContextCompilationError,
    compile_l0_company_context,
)


L1_CONTEXT_SCHEMA = "company-context.l1.v1"

DEFAULT_L1_MAX_CONTEXT_TOKENS = 16000
DEFAULT_L1_RESERVED_OUTPUT_TOKENS = 3000

MAX_PROJECT_MEMORIES = 200
MAX_PROJECT_TASKS = 500

_OPEN_TASK_STATUSES = frozenset({
    "draft",
    "planned",
    "queued",
    "running",
    "blocked",
    "needs_review",
    "verified",
    "approved",
    "failed",
})

_MEMORY_KIND_ORDER = {
    "requirement": 10,
    "decision": 20,
    "policy": 30,
    "risk": 40,
    "lesson": 50,
    "future_work": 60,
    "note": 70,
}

_TOKEN_ESTIMATION_METHOD = (
    "ceil(UTF-8 canonical JSON bytes / 3); deterministic heuristic, "
    "not an exact provider tokenizer"
)

# This is a conservative pattern preflight, not a complete DLP engine.
# The error messages never include the matched value.
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|"
        r"github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxai-[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(
        r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b",
        re.IGNORECASE,
    ),
)


class L1ContextCompilationError(ContextCompilationError):
    """L1 cannot safely construct a complete project context."""


class L1ContextBudgetExceeded(L1ContextCompilationError):
    """The complete L1 packet exceeds the available context budget."""

    def __init__(self, estimated_tokens: int, available_tokens: int) -> None:
        self.estimated_tokens = estimated_tokens
        self.available_tokens = available_tokens
        super().__init__(
            "Complete L1 project context exceeds the available token budget: "
            f"estimated={estimated_tokens}, available={available_tokens}. "
            "The compiler did not silently truncate project knowledge or tasks."
        )


class L1ContextSelectionLimitExceeded(L1ContextCompilationError):
    """The project data exceeds the bounded retrieval contract."""


class L1ContextSensitiveDataError(L1ContextCompilationError):
    """A known credential-like value was found in a selected record."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _estimate_tokens(value: Any) -> int:
    encoded = _canonical_json(value).encode("utf-8")
    return max(1, math.ceil(len(encoded) / 3))


def _validate_budget(
    max_context_tokens: int,
    reserved_output_tokens: int,
) -> tuple[int, int, int]:
    for field, value, minimum in (
        ("max_context_tokens", max_context_tokens, 1),
        ("reserved_output_tokens", reserved_output_tokens, 0),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise L1ContextCompilationError(f"{field} must be an integer.")
        if value < minimum:
            raise L1ContextCompilationError(
                f"{field} must be greater than or equal to {minimum}."
            )

    available = max_context_tokens - reserved_output_tokens
    if available <= 0:
        raise L1ContextCompilationError(
            "reserved_output_tokens must be smaller than max_context_tokens."
        )

    return max_context_tokens, reserved_output_tokens, available


def _assert_no_sensitive_values(value: Any, record_reference: str) -> None:
    """Inspect selected values without returning or logging matched secrets."""
    if isinstance(value, str):
        for pattern in _SENSITIVE_VALUE_PATTERNS:
            if pattern.search(value):
                raise L1ContextSensitiveDataError(
                    "Context export refused because a credential-like value "
                    f"was detected in record {record_reference}. "
                    "Remove the sensitive value from project memory and retry."
                )
        return

    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_no_sensitive_values(
                child,
                f"{record_reference}.{key}",
            )
        return

    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_no_sensitive_values(
                child,
                f"{record_reference}[{index}]",
            )


def _read_consistent_project_snapshot(
    foundation: FoundationService,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Read counts and rows from one SQLite read snapshot.

    The count checks prevent the MemoryStore API's bounded list operations
    from silently returning a partial project history.
    """
    database_path = Path(foundation.memory.db_path)

    if not database_path.is_file():
        raise L1ContextCompilationError(
            "The canonical project-memory database is missing."
        )

    connection = sqlite3.connect(
        str(database_path),
        timeout=15,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=15000")

    try:
        connection.execute("BEGIN")

        memory_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM memories
                WHERE scope='project' AND archived=0
                """
            ).fetchone()[0]
        )
        task_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM tasks"
            ).fetchone()[0]
        )

        if memory_count > MAX_PROJECT_MEMORIES:
            raise L1ContextSelectionLimitExceeded(
                "Project memory contains "
                f"{memory_count} active records; the current L1 retrieval "
                f"limit is {MAX_PROJECT_MEMORIES}. No partial packet was returned."
            )

        if task_count > MAX_PROJECT_TASKS:
            raise L1ContextSelectionLimitExceeded(
                f"The task backlog contains {task_count} records; the current "
                f"L1 retrieval limit is {MAX_PROJECT_TASKS}. No partial packet "
                "was returned."
            )

        memory_rows = connection.execute(
            """
            SELECT *
            FROM memories
            WHERE scope='project' AND archived=0
            ORDER BY memory_id ASC
            """
        ).fetchall()

        task_rows = connection.execute(
            """
            SELECT *
            FROM tasks
            ORDER BY
                CASE priority
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2
                    ELSE 3
                END,
                updated_at DESC,
                task_id ASC
            """
        ).fetchall()

        if len(memory_rows) != memory_count or len(task_rows) != task_count:
            raise L1ContextCompilationError(
                "The project-memory snapshot was incomplete; compilation stopped."
            )

        memories: list[dict[str, Any]] = []
        for row in memory_rows:
            item = dict(row)
            try:
                item["tags"] = json.loads(item.pop("tags_json"))
            except (TypeError, json.JSONDecodeError) as exc:
                raise L1ContextCompilationError(
                    f"Project memory record {item.get('memory_id')} has invalid tags."
                ) from exc

            if not isinstance(item["tags"], list):
                raise L1ContextCompilationError(
                    f"Project memory record {item.get('memory_id')} has invalid tags."
                )

            memories.append(item)

        tasks: list[dict[str, Any]] = []
        for row in task_rows:
            item = dict(row)
            try:
                item["acceptance_criteria"] = json.loads(
                    item.pop("acceptance_json")
                )
                item["depends_on"] = json.loads(
                    item.pop("depends_on_json")
                )
            except (TypeError, json.JSONDecodeError) as exc:
                raise L1ContextCompilationError(
                    f"Task {item.get('task_id')} contains invalid JSON fields."
                ) from exc

            if (
                not isinstance(item["acceptance_criteria"], list)
                or not isinstance(item["depends_on"], list)
            ):
                raise L1ContextCompilationError(
                    f"Task {item.get('task_id')} contains invalid list fields."
                )

            tasks.append(item)

        return memories, tasks, {
            "project_memories": memory_count,
            "tasks": task_count,
        }

    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise L1ContextCompilationError(
            f"Could not read a consistent project-memory snapshot: {exc}"
        ) from exc
    finally:
        connection.close()


def _normalise_memory(item: Mapping[str, Any]) -> dict[str, Any]:
    required_text = ("kind", "title", "content", "source")
    for field in required_text:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise L1ContextCompilationError(
                f"Project memory record {item.get('memory_id')} has an empty {field}."
            )

    memory_id = item.get("memory_id")
    if isinstance(memory_id, bool) or not isinstance(memory_id, int):
        raise L1ContextCompilationError(
            "A project-memory record has an invalid memory ID."
        )

    result = {
        "memory_id": memory_id,
        "kind": item["kind"],
        "title": item["title"],
        "content": item["content"],
        "source": item["source"],
        "tags": item["tags"],
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
    }

    _assert_no_sensitive_values(result, f"project_memory:{memory_id}")
    return result


def _normalise_task(item: Mapping[str, Any]) -> dict[str, Any]:
    task_id = item.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise L1ContextCompilationError("A task has an invalid task ID.")

    status = item.get("status")
    if status not in TASK_STATUSES:
        raise L1ContextCompilationError(
            f"Task {task_id} contains an unsupported status."
        )

    priority = item.get("priority")
    if priority not in {"critical", "high", "normal", "low"}:
        raise L1ContextCompilationError(
            f"Task {task_id} contains an unsupported priority."
        )

    result = {
        "task_id": task_id,
        "title": item.get("title", ""),
        "description": item.get("description", ""),
        "agent_id": item.get("agent_id"),
        "status": status,
        "priority": priority,
        "acceptance_criteria": item["acceptance_criteria"],
        "depends_on": item["depends_on"],
        "next_action": item.get("next_action", ""),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }

    if not isinstance(result["title"], str) or not result["title"].strip():
        raise L1ContextCompilationError(
            f"Task {task_id} has an empty title."
        )

    if not isinstance(result["description"], str):
        raise L1ContextCompilationError(
            f"Task {task_id} has an invalid description."
        )

    if not isinstance(result["acceptance_criteria"], list) or not all(
        isinstance(value, str) for value in result["acceptance_criteria"]
    ):
        raise L1ContextCompilationError(
            f"Task {task_id} has invalid acceptance criteria."
        )

    if not isinstance(result["depends_on"], list) or not all(
        isinstance(value, str) for value in result["depends_on"]
    ):
        raise L1ContextCompilationError(
            f"Task {task_id} has invalid dependency references."
        )

    _assert_no_sensitive_values(result, f"task:{task_id}")
    return result


def _finalise_packet(
    core_packet: Mapping[str, Any],
    *,
    max_context_tokens: int,
    reserved_output_tokens: int,
) -> dict[str, Any]:
    maximum, reserve, available = _validate_budget(
        max_context_tokens,
        reserved_output_tokens,
    )

    budget: dict[str, Any] = {
        "max_context_tokens": maximum,
        "reserved_output_tokens": reserve,
        "available_context_tokens": available,
        "estimated_context_tokens": 0,
        "estimation_method": _TOKEN_ESTIMATION_METHOD,
        "truncated": False,
        "omitted_sections": [],
    }

    packet: dict[str, Any] = {
        **dict(core_packet),
        "budget": budget,
        "packet_sha256": "0" * 64,
    }

    converged = False
    for _ in range(8):
        estimate = _estimate_tokens(packet)
        if budget["estimated_context_tokens"] == estimate:
            converged = True
            break
        budget["estimated_context_tokens"] = estimate

    final_estimate = _estimate_tokens(packet)
    if (
        not converged
        or final_estimate != budget["estimated_context_tokens"]
    ):
        raise L1ContextCompilationError(
            "L1 token-budget estimation did not converge deterministically."
        )

    if final_estimate > available:
        raise L1ContextBudgetExceeded(final_estimate, available)

    unsigned_packet = dict(packet)
    unsigned_packet.pop("packet_sha256")
    packet["packet_sha256"] = hashlib.sha256(
        _canonical_json(unsigned_packet).encode("utf-8")
    ).hexdigest()

    return packet


def compile_l1_project_context(
    foundation: FoundationService,
    *,
    max_context_tokens: int = DEFAULT_L1_MAX_CONTEXT_TOKENS,
    reserved_output_tokens: int = DEFAULT_L1_RESERVED_OUTPUT_TOKENS,
) -> dict[str, Any]:
    """Compile a complete, deterministic L1 project context.

    The compiler validates L0 first, then reads all active project memories
    and tasks within explicit retrieval limits. It never mutates memory.
    """
    maximum, reserve, _ = _validate_budget(
        max_context_tokens,
        reserved_output_tokens,
    )

    # L0 is the required parent and canonical identity boundary.
    try:
        parent_context = compile_l0_company_context(
            foundation,
            max_context_tokens=maximum,
            reserved_output_tokens=reserve,
        )
    except ContextCompilationError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise L1ContextCompilationError(
            f"Could not compile the required L0 parent context: {exc}"
        ) from exc

    memories, tasks, record_counts = _read_consistent_project_snapshot(
        foundation
    )

    normalised_memories = [
        _normalise_memory(item)
        for item in memories
    ]
    normalised_tasks = [
        _normalise_task(item)
        for item in tasks
    ]

    normalised_memories.sort(
        key=lambda item: (
            _MEMORY_KIND_ORDER.get(item["kind"], 90),
            -item["memory_id"],
        )
    )

    knowledge_by_kind: dict[str, list[dict[str, Any]]] = {}
    for item in normalised_memories:
        kind = item["kind"]
        knowledge_by_kind.setdefault(kind, []).append(item)

    task_counts = Counter(
        item["status"] for item in normalised_tasks
    )
    status_counts = {
        status: task_counts.get(status, 0)
        for status in TASK_STATUSES
    }
    open_task_count = sum(
        1
        for item in normalised_tasks
        if item["status"] in _OPEN_TASK_STATUSES
    )

    source_manifest = [
        {
            "source_id": f"project_memory:{item['memory_id']}",
            "source_type": "project_memory",
            "record_id": item["memory_id"],
            "kind": item["kind"],
            "updated_at": item["updated_at"],
        }
        for item in normalised_memories
    ]
    source_manifest.extend(
        {
            "source_id": f"task:{item['task_id']}",
            "source_type": "project_task",
            "record_id": item["task_id"],
            "updated_at": item["updated_at"],
        }
        for item in normalised_tasks
    )

    core_packet = {
        "schema": L1_CONTEXT_SCHEMA,
        "level": "L1",
        "purpose": (
            "Project continuity: authoritative project identity, stored "
            "requirements and decisions, project knowledge, and task state."
        ),
        "parent_context": parent_context,
        "project": {
            "identity": parent_context["primary_project"],
            "knowledge": {
                "by_kind": knowledge_by_kind,
                "record_count": len(normalised_memories),
                "kind_counts": {
                    kind: len(items)
                    for kind, items in sorted(knowledge_by_kind.items())
                },
            },
            "task_backlog": {
                "record_count": len(normalised_tasks),
                "open_task_count": open_task_count,
                "status_counts": status_counts,
                "tasks": normalised_tasks,
            },
        },
        "retrieval": {
            "mode": "complete_project_scope_snapshot",
            "scope": "project",
            "read_only": True,
            "consistent_sqlite_read_snapshot": True,
            "records_available": record_counts,
            "records_included": {
                "project_memories": len(normalised_memories),
                "tasks": len(normalised_tasks),
            },
            "limits": {
                "project_memories": MAX_PROJECT_MEMORIES,
                "tasks": MAX_PROJECT_TASKS,
            },
            "complete": True,
            "omitted_records": 0,
            "omitted_sections": [],
        },
        "security_preflight": {
            "credential_pattern_check": "passed",
            "matched_values_disclosed": False,
            "limitation": (
                "Known credential patterns are checked before export. "
                "This is not a complete secret-scanning or DLP system."
            ),
        },
        "sources": source_manifest,
        "compiler_contract": {
            "memory_mutated": False,
            "model_provider_called": False,
            "task_executed": False,
            "token_estimation": _TOKEN_ESTIMATION_METHOD,
        },
    }

    return _finalise_packet(
        core_packet,
        max_context_tokens=maximum,
        reserved_output_tokens=reserve,
    )


def write_l1_context_packet(
    packet: Mapping[str, Any],
    destination: str | os.PathLike[str],
) -> Path:
    """Verify and atomically write an L1 packet as UTF-8 JSON."""
    if packet.get("schema") != L1_CONTEXT_SCHEMA:
        raise L1ContextCompilationError(
            "Refusing to write a packet with an unsupported L1 schema."
        )

    supplied_digest = packet.get("packet_sha256")
    if (
        not isinstance(supplied_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", supplied_digest)
    ):
        raise L1ContextCompilationError(
            "Refusing to write an L1 packet without a valid SHA-256 digest."
        )

    unsigned_packet = dict(packet)
    unsigned_packet.pop("packet_sha256", None)

    expected_digest = hashlib.sha256(
        _canonical_json(unsigned_packet).encode("utf-8")
    ).hexdigest()

    if supplied_digest != expected_digest:
        raise L1ContextCompilationError(
            "Refusing to write an L1 packet whose digest does not match."
        )

    output = Path(destination).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    serialized = json.dumps(
        dict(packet),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary_path, output)
        temporary_path = None

    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return output
