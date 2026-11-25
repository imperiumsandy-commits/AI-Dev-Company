"""Version-controlled operating policies for the AI-Dev-Company L0 context.

These are company-level guardrails, not a claim that every policy already has
an automated enforcement mechanism. ``enforcement_state`` states the current
implementation boundary explicitly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


POLICY_CATALOG_VERSION = "1.1.0"
POLICY_CATALOG_SOURCE = "company_os/context/company_policies.py"


@dataclass(frozen=True, slots=True)
class OperatingPolicy:
    policy_id: str
    title: str
    domain: str
    priority: int
    rule: str
    enforcement_state: str
    limitation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


COMPANY_OPERATING_POLICIES: tuple[OperatingPolicy, ...] = (
    OperatingPolicy(
        policy_id="company.project_separation",
        title="Keep company projects and identities separate",
        domain="company_governance",
        priority=10,
        rule=(
            "AI-Dev-Company is an independent project. Do not merge its "
            "repository, architecture, specialist identities, execution state, "
            "or project memory with Intellect Media or another project."
        ),
        enforcement_state="documented_context_policy",
        limitation=(
            "This L0 policy communicates the boundary; cross-project storage "
            "isolation still requires dedicated runtime and authorization tests."
        ),
    ),
    OperatingPolicy(
        policy_id="company.specialist_independence",
        title="Preserve eight independent specialist domains",
        domain="agent_governance",
        priority=20,
        rule=(
            "Keep Business Analyst / PM, System Architect, Backend Developer, "
            "Frontend Developer, Database Administrator, Cybersecurity "
            "Engineer, QA / Bug Hunter, and DevOps Engineer as distinct roles. "
            "Shared infrastructure may coordinate them, but must not collapse "
            "their domain reasoning, ownership, permissions, or independent "
            "verification into one generic agent."
        ),
        enforcement_state="canonical_registry_catalog_and_validated_specs",
        limitation=(
            "The registry proves specialist identities and the manifest loader "
            "validates their specifications. Registration and specification "
            "readiness are not executable activation; shared runtime and "
            "domain evaluation are still pending."
        ),
    ),
    OperatingPolicy(
        policy_id="engineering.evidence_before_completion",
        title="Evidence before completion",
        domain="engineering_quality",
        priority=30,
        rule=(
            "Treat externally generated AI output as a draft. Review it against "
            "requirements, inspect failure cases, and run relevant verification. "
            "Never report a test, security review, deployment, or acceptance "
            "gate as successful without recorded evidence from that check."
        ),
        enforcement_state="ci_regression_gate",
        limitation=(
            "Current CI compiles the Python packages and runs pytest. It does "
            "not yet provide independent AI review, full security scanning, "
            "or production acceptance evidence."
        ),
    ),
    OperatingPolicy(
        policy_id="engineering.first_pass_excellence",
        title="Deliver first-pass, production-minded, non-generic engineering",
        domain="engineering_quality",
        priority=35,
        rule=(
            "Before changing code, inspect the actual current main-branch source, "
            "affected modules, callers, public contracts, dependencies, tests, "
            "configuration, workflows, and relevant documentation. Define "
            "acceptance criteria and compatibility constraints before editing. "
            "Deliver one consolidated end-to-end feature batch containing all "
            "required source, tests, contracts, migrations, failure paths, and "
            "documentation changes. Do not split a known complete feature into "
            "avoidable partial deliveries that force repeated replacement of "
            "the same file. Minimize file churn without omitting required work. "
            "Design each specialist and component for its actual domain rather "
            "than generic demos, prompt templates, placeholder integrations, "
            "fake functionality, dead documentation, or unused abstractions. "
            "Evaluate correctness, security, privacy, data integrity, "
            "compatibility, concurrency, recovery, observability, performance, "
            "accessibility, and operational safety wherever relevant. Derive "
            "tests from acceptance criteria and risk, including negative, "
            "boundary, failure-cleanup, and concurrency cases where applicable. "
            "Run targeted tests and the complete available regression suite. "
            "Inspect the exact commit's CI result before declaring completion. "
            "Report verified evidence and remaining limitations honestly."
        ),
        enforcement_state="documented_l0_company_policy_and_regression_tests",
        limitation=(
            "This policy is delivered into canonical L0 context and regression "
            "tests. The repository does not yet have a complete independent "
            "AI review/refinement engine or automated gates for every quality "
            "dimension. CI and policy presence do not alone prove production "
            "readiness."
        ),
    ),
    OperatingPolicy(
        policy_id="delivery.github_is_source_of_truth",
        title="GitHub-first source delivery",
        domain="repository_governance",
        priority=40,
        rule=(
            "The imperiumsandy-commits/AI-Dev-Company main branch is the "
            "authoritative merged source state. Deliver additions and "
            "replacements as complete repository-relative files in chat. The "
            "repository owner applies changes manually through GitHub. The "
            "assistant must not write, commit, or push repository changes. "
            "Normal additions must not depend on local-PC or PowerShell work."
        ),
        enforcement_state="delivery_process_contract",
        limitation=(
            "This is a workflow boundary for collaborators; it is not an "
            "automated GitHub permission policy implemented by this compiler."
        ),
    ),
    OperatingPolicy(
        policy_id="security.credential_boundary",
        title="Keep credentials outside source and context",
        domain="security",
        priority=50,
        rule=(
            "Never place provider keys, passwords, access tokens, private "
            "credentials, or secret values in ordinary project memory, source "
            "files, logs, audit payloads, or compiled context packets. Use "
            "authorized secret references and least-privilege access."
        ),
        enforcement_state="partial_registry_guard_and_context_preflight",
        limitation=(
            "Known secret-like patterns are rejected by registry validation "
            "and L1 context preflight. Heuristic detection is not exhaustive "
            "protection for every unknown secret format or future data path."
        ),
    ),
    OperatingPolicy(
        policy_id="governance.high_risk_owner_approval",
        title="Require owner approval for high-risk actions",
        domain="governance",
        priority=60,
        rule=(
            "Require explicit authorized owner approval before production "
            "deployment, destructive data changes, database migrations, "
            "company-wide permission changes, sensitive security-policy "
            "changes, or external spending. Fail closed when the required "
            "authorization cannot be verified."
        ),
        enforcement_state="not_yet_enforced_end_to_end",
        limitation=(
            "The complete approval service, actor authorization model, and "
            "execution-time enforcement gate are still pending. This policy "
            "must not be represented as an already active approval system."
        ),
    ),
    OperatingPolicy(
        policy_id="truth.registration_is_not_activation",
        title="Report implementation and activation truthfully",
        domain="operational_integrity",
        priority=70,
        rule=(
            "Distinguish documented, implemented, tested, registered, "
            "specification-ready, runtime-ready, evaluated, and active states. "
            "A registry row or loaded instruction file does not prove that an "
            "AI agent is being invoked or can execute work. Do not claim "
            "provider execution, cloud-shared memory, or autonomous operation "
            "until implemented and verified."
        ),
        enforcement_state="context_disclosure_registry_lifecycle_and_spec_validation",
        limitation=(
            "The current repository contains a local memory prototype, "
            "validated specialist specifications and context compilers, not "
            "a complete agent executor or provider gateway."
        ),
    ),
    OperatingPolicy(
        policy_id="memory.context_ownership",
        title="Keep canonical memory and compiled context separate",
        domain="data_governance",
        priority=80,
        rule=(
            "Persistent Memory owns approved project knowledge, decisions, "
            "requirements, lessons, tasks, and checkpoints. Repository "
            "Intelligence owns technical observations. A context compiler may "
            "read and assemble verified information, but must not silently "
            "rewrite canonical project memory."
        ),
        enforcement_state="separate_store_and_read_only_compiler_contract",
        limitation=(
            "Registry and memory currently use separate local SQLite "
            "databases. Their binding is validated, but they are not one "
            "distributed atomic transaction or cloud-shared store."
        ),
    ),
    OperatingPolicy(
        policy_id="repository.command_output_is_not_source",
        title="Treat command-output snapshots as historical evidence",
        domain="repository_governance",
        priority=90,
        rule=(
            "PS-Output and similarly named command-output snapshots are "
            "historical diagnostic evidence only. Do not treat them as "
            "application modules, executable source, or authoritative "
            "implementation instructions."
        ),
        enforcement_state="repository_documentation_contract",
        limitation=(
            "The scanner and compiler do not execute these files, but a "
            "complete repository policy scanner is not part of L0."
        ),
    ),
)


def validate_policy_catalog() -> None:
    """Reject duplicate, empty, or unstable policy definitions."""
    ids = [policy.policy_id for policy in COMPANY_OPERATING_POLICIES]
    priorities = [policy.priority for policy in COMPANY_OPERATING_POLICIES]

    if len(ids) != len(set(ids)):
        raise ValueError("Operating policy IDs must be unique.")
    if len(priorities) != len(set(priorities)):
        raise ValueError("Operating policy priorities must be unique.")

    for policy in COMPANY_OPERATING_POLICIES:
        required_text = (
            policy.policy_id,
            policy.title,
            policy.domain,
            policy.rule,
            policy.enforcement_state,
            policy.limitation,
        )
        if any(
            not isinstance(value, str) or not value.strip()
            for value in required_text
        ):
            raise ValueError(
                "Operating policy identity, rule, and limitation fields "
                "must not be empty."
            )
        if isinstance(policy.priority, bool) or not isinstance(
            policy.priority,
            int,
        ):
            raise ValueError("Operating policy priority must be an integer.")
        if policy.priority < 1:
            raise ValueError(
                "Operating policy priority must be a positive integer."
            )
