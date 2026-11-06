"""CLI for bootstrapping and inspecting the F01 registry."""

from __future__ import annotations

import argparse
import json

from .catalog import DEFAULT_AGENTS
from .core import RegistryStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="company-registry",
        description="AI-Dev-Company F01 registry",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    boot = commands.add_parser(
        "bootstrap",
        help="Register the company, project and eight specialist agents atomically",
    )

    boot.add_argument(
        "--db",
        default=".ai-dev-company/company_registry.sqlite3",
    )
    boot.add_argument(
        "--company-id",
        default="co_ai_dev_company",
    )
    boot.add_argument(
        "--company-slug",
        default="ai-dev-company",
    )
    boot.add_argument(
        "--name",
        default="AI Software Engineering Company",
    )
    boot.add_argument(
        "--owner-name",
        default="Sandip",
    )
    boot.add_argument("--owner-email", required=True)

    boot.add_argument(
        "--project-id",
        default="prj_ai_dev_company",
    )
    boot.add_argument(
        "--project-slug",
        default="ai-dev-company",
    )
    boot.add_argument(
        "--project-name",
        default="AI-Dev-Company",
    )
    boot.add_argument("--repository-url", required=True)
    boot.add_argument(
        "--default-branch",
        default="main",
    )

    boot.add_argument(
        "--actor",
        default="owner:imperiumsandy-commits",
    )
    boot.add_argument(
        "--reason",
        default="Initial F01 registry bootstrap",
    )

    listing = commands.add_parser(
        "list",
        help="List one company's registered projects and agents",
    )
    listing.add_argument(
        "--db",
        default=".ai-dev-company/company_registry.sqlite3",
    )
    listing.add_argument("--company-id", required=True)

    check = commands.add_parser(
        "integrity",
        help="Validate SQLite, foreign keys and audit hash chain",
    )
    check.add_argument(
        "--db",
        default=".ai-dev-company/company_registry.sqlite3",
    )
    check.add_argument("--company-id", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    registry = RegistryStore(args.db)

    if args.command == "bootstrap":
        result = registry.bootstrap(
            company={
                "company_id": args.company_id,
                "slug": args.company_slug,
                "name": args.name,
                "owner_name": args.owner_name,
                "owner_email": args.owner_email,
            },
            project={
                "project_id": args.project_id,
                "company_id": args.company_id,
                "slug": args.project_slug,
                "name": args.project_name,
                "repository_url": args.repository_url,
                "default_branch": args.default_branch,
            },
            agents=DEFAULT_AGENTS,
            actor=args.actor,
            reason=args.reason,
        )

        print(json.dumps(result, indent=2))
        return 0

    if args.command == "list":
        print(
            json.dumps(
                {
                    "company": registry.get_company(args.company_id),
                    "projects": registry.list_projects(args.company_id),
                    "agents": registry.list_agents(args.company_id),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "integrity":
        result = registry.validate(args.company_id)
        print(json.dumps(result, indent=2))
        return 0 if result["valid"] else 2

    parser.error("Unsupported command")
    return 2
