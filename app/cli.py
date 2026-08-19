from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.config import get_settings
from app.container import build_container


def main() -> None:
    parser = argparse.ArgumentParser(prog="decision-intel")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-workspace", help="Create a workspace")
    create.add_argument("workspace_id")
    create.add_argument("--name", default=None)
    create.add_argument("--description", default="")

    ingest = sub.add_parser("ingest", help="Ingest files into a workspace")
    ingest.add_argument("workspace_id")
    ingest.add_argument("--path", action="append", default=[], type=Path)
    ingest.add_argument("--github", default=None)

    args = parser.parse_args()
    container = build_container(get_settings())

    if args.command == "create-workspace":
        workspace = container.workspaces.create(
            args.name or args.workspace_id, args.description, args.workspace_id
        )
        print(f"created workspace {workspace.workspace_id}")
        return

    workspace = container.workspaces.ensure(args.workspace_id)
    result = asyncio.run(
        container.ingestion.ingest(
            workspace.workspace_id, paths=args.path, github_repository=args.github
        )
    )
    print(f"ingested {result.documents_ingested} documents into {result.dataset}")


if __name__ == "__main__":
    main()
