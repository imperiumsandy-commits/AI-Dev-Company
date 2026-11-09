# AI-Dev-Company

**An AI Software Engineering Company OS**

AI-Dev-Company is an engineering platform designed to coordinate eight independent AI software specialists through shared company infrastructure, persistent project knowledge, repository intelligence, controlled execution, and evidence-based quality gates.

The objective is not to create one generic chatbot that pretends to be eight developers. Each specialist will have its own domain responsibilities, architecture, tools, evaluation criteria, and execution boundaries.

---

## 1. Project Identity

| Property | Value |
|---|---|
| Project | AI-Dev-Company |
| Organization | imperiumsandy-commits |
| Repository | AI-Dev-Company |
| Primary branch | main |
| Platform | AI Software Engineering Company OS |
| Primary language | Python |
| Current development stage | Foundation implementation |
| Current CI | GitHub Actions |
| Current test framework | pytest |

The original GitHub repository is the project's source of truth:

https://github.com/imperiumsandy-commits/AI-Dev-Company

This project is independent from Intellect Media. Its architecture, agents, repository history, and memory must remain separate.

## 2. Engineering Mission

Build a professional AI engineering organization capable of supporting the complete software development lifecycle:

1. Business discovery and requirements analysis.
2. Product planning and dependency management.
3. System architecture and technical design.
4. Backend and frontend development.
5. Database design and management.
6. Cybersecurity analysis.
7. Independent quality assurance.
8. Deployment and operational reliability.

The platform must preserve project history, verify work, detect regressions, and improve AI-generated implementation rather than accepting unverified output.

## 3. Eight Independent Specialists

| Specialist | Primary responsibility |
|---|---|
| Business Analyst / PM | Requirements, planning, backlog, coordination |
| System Architect | System design, contracts, technical decisions |
| Backend Developer | APIs, business logic, services |
| Frontend Developer | User interfaces, frontend architecture |
| Database Administrator | Data models, migrations, performance |
| Cybersecurity Engineer | Threat analysis, security controls |
| QA / Bug Hunter | Independent testing, defect discovery |
| DevOps Engineer | CI/CD, infrastructure, deployment |

Each specialist must eventually own:

- Its own role definition.
- Domain-specific architecture.
- Workflow and decision policies.
- Tools and permissions.
- Input and output contracts.
- Evaluation scenarios.
- Domain-specific tests.
- Specialist memory and work history.

Shared infrastructure must coordinate specialists without mixing their domain logic.

**Important:** Registry entries do not mean executable agents are already active. Each agent must pass implementation and evaluation gates before being declared operational.

## 4. Current Repository Architecture

### Company OS

`company_os/registry/`

Company, project, and agent registration, versioned configuration, status management, and append-only audit events.

`company_os/context/`

- Repository inventory and content hashing.
- Python dependency mapping.
- Git change and historical revision analysis.
- Direct and transitive change-impact analysis.
- Incremental scan cache and strict verification.
- L0 company context compilation from validated registry state.
- Version-controlled company operating-policy catalog.
- Deterministic context serialization, integrity digest, and explicit heuristic token budget.

The L0 compiler contains company identity, the canonical primary project, the eight specialist records, specification-readiness status, operating policies, and current storage boundaries. It does not compile L1-L4 task or specialist context.

### Existing Active Memory Prototype

`ai_dev_company/`

- `memory_store.py` — SQLite-based project memory, tasks, events, and checkpoints.
- `agent_loader.py` — Loads specialist instructions from the expected agent directory.
- `cli.py` — Memory and agent-context commands.

This is a local SQLite prototype. It is not yet a cloud-shared memory system.

### Tests

`tests/`

Automated tests cover registry contracts, memory, repository scanning, dependencies, incremental scanning, change impact, integrated foundation behaviour, and the L0 company context contract.

### Other Existing Files

- `Foundation plan` — Company OS architecture and implementation roadmap.
- `business-analyst-pm-batch-01-source.md` — Business Analyst / PM implementation source material.
- `PS-Output` — Historical command-output snapshot, not an executable project module.

## 5. Foundation Implementation Status

| Component | Current evidence | Status |
|---|---|---|
| F01 Registry | SQLite registry, canonical eight-specialist contract, transactional bootstrap, audit-chain validation, regression tests | Implemented prototype; latest verified baseline CI passed |
| F02 Repository intelligence | Scanner, dependencies, Git and impact analysis, incremental scan cache | Implemented prototype |
| F03 Persistent memory | Local SQLite memories, tasks, events, checkpoints, and retry-safe Foundation bindings | Partial; local-only storage |
| F04 Context compiler | L0 company packet, policy catalog, deterministic serialization, digest, heuristic token budget | Partial; L1-L4 retrieval and compilation remain pending |
| F05 Incremental audit | Incremental scan cache and strict verification primitives | Partial; complete engineering evidence ledger and invalidation remain pending |
| Governance | Registry audit events and configuration guardrails | Partial; full authorization and high-risk approval service missing |
| F06 Agent runtime | Basic specification loader and eight registry identities | Pending; no shared executor or provider gateway |
| F07 Quality engine | CI and regression tests | Partial; independent AI review/refinement and full security gates missing |
| F08 BA / PM activation | Source material exists | Pending; integrated specialist package, runtime, and evaluations missing |

These statuses describe the repository's implemented scope, not future commitments. A successful CI run verifies only the checks executed by that workflow.

## 6. Architecture Principles

### Single source of truth

The GitHub repository is the source of truth for implementation.

Runtime databases, credentials, generated indexes, and execution artifacts must not be committed as ordinary source files.

### Evidence before completion

A task is not complete merely because code was written.

Completion requires:

- Implementation review.
- Relevant regression tests.
- Successful automated verification.
- Acceptance criteria.
- Recorded unresolved risks.
- Independent approval when required.

### Controlled context

L0 provides verified company identity and company-wide operating policies. Later context levels add project requirements, specialist contracts, task-specific source and dependency information, and deep verification evidence. The compiler must disclose scope and omitted sections rather than imply that L0 is a complete project context.

### Independent specialist ownership

The Backend Developer must not inherit the complete responsibilities of the System Architect, DBA, or Cybersecurity Engineer.

The shared execution platform coordinates their work.

### Incremental engineering

Existing tested modules must be reused.

New modules must have clearly justified responsibilities.

Related source and test changes must be delivered together.

### Recoverability

Tasks, decisions, state transitions, failures, and checkpoints must survive process restarts and be recoverable from verified persistent storage.

## 7. Development Workflow

The required development process is:

1. Inspect the actual GitHub source.
2. Identify existing modules and dependencies.
3. Define the complete feature boundary.
4. Prepare a consolidated implementation batch.
5. Update existing source and related tests together.
6. Review the complete batch for regression and architectural consistency.
7. Apply the changes through the GitHub browser interface.
8. Run and inspect the GitHub Actions verification.
9. Merge or retain changes only after the required verification succeeds.
10. Re-read the updated source before starting dependent work.

The owner edits files manually through the GitHub browser interface.

The assistant provides complete file contents directly in chat.

The assistant must not write, commit, or push to GitHub.

Local PC setup, PowerShell scripts, and local Git publishing are not required for normal project development.

## 8. Quality Gates

A feature must satisfy:

- Correct package imports.
- Python compilation.
- Existing regression tests.
- New behaviour-specific tests.
- Validation of negative and failure cases.
- Dependency and contract consistency.
- Appropriate security checks.
- Documentation consistency.
- Successful GitHub Actions verification.

A schema or public interface change must update every affected consumer and test in the same batch.

## 9. GitHub Actions

Primary CI workflow:

`.github/workflows/python-ci.yml`

The workflow uses Python 3.12, compiles project packages and tests, executes pytest, and uploads a test-result artifact.

GitHub Actions is the authoritative automated verification environment for repository changes.

Never declare a test suite successful without actual execution evidence. A successful CI run verifies only the checks executed by that workflow; it does not automatically certify every architecture or product acceptance criterion.

## 10. Current Known Limitations

The current implementation is not yet a production-ready autonomous engineering company.

Outstanding engineering work includes:

- L1-L4 context compilation, retrieval ranking, source-level context selection, and provider-aware tokenization. L0 uses a documented byte-based token estimate, not an exact model tokenizer.
- Complete audit evidence storage, source/test evidence invalidation, and approval binding.
- Recovery and execution orchestration.
- Eight independent specialist specification packages, evaluation scenarios, and a shared runtime.
- Model-provider integration and provider-specific capability handling.
- Enforceable security authorization and high-risk owner approval.
- Independent AI code review and evidence-backed refinement.
- Production deployment and monitoring.
- Shared multi-session storage.

The registry and memory are separate local SQLite databases. Foundation bindings validate their company/project identity, but do not create a distributed atomic transaction. PostgreSQL is a future architectural target, not an already integrated dependency.

The current agent loader only reads specification files. It does not invoke a model or execute an agent. The current repository tree still needs the eight independently authored specification directories.

## 11. L0 Context Compilation

The current first context level is compiled from validated Foundation state:

- Company identity and status from the canonical registry.
- Primary project identity, repository URL, and default branch from the canonical registry.
- Exactly eight registered specialist records in canonical roster order.
- A read-only summary of each specialist's specification readiness.
- Version-controlled company operating policies with explicit enforcement status and limitations.
- The current two-database SQLite storage boundary.

The compiler refuses to produce a packet when Foundation validation fails, when the registered roster does not match the canonical catalog, or when required L0 content exceeds the available context budget. It does not silently truncate company identity or policy rules, and it does not write to project memory.

Run from an initialized repository after the integrated Foundation has been bootstrapped:

```bash
python -m company_os.context.l0_cli --root .
