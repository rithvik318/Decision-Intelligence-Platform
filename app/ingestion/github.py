"""Bounded, read-only GitHub loader.

Kept because it already existed, but it is only one source among many: the
ingestion layer stays source-agnostic and GitHub is not central to the product.
"""

from __future__ import annotations

import base64

import httpx

from app.config import Settings
from app.domain import SourceDocument

API = "https://api.github.com"
MAX_FILES = 30
RELEVANT_SUFFIXES = (".md", ".txt", ".py", ".ts", ".tsx", ".js", ".toml", ".yaml", ".yml")


class GitHubLoader:
    def __init__(self, settings: Settings) -> None:
        self._token = settings.github_token

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def load(self, repository: str) -> list[SourceDocument]:
        if "/" not in repository:
            raise ValueError("repository must be in 'owner/name' form")
        documents: list[SourceDocument] = []
        async with httpx.AsyncClient(
            base_url=API, headers=self._headers(), timeout=30.0
        ) as client:
            meta = (await client.get(f"/repos/{repository}")).json()
            documents.append(
                SourceDocument(
                    content=(
                        f"Repository {repository}\n"
                        f"Description: {meta.get('description') or 'n/a'}\n"
                        f"Primary language: {meta.get('language') or 'n/a'}\n"
                        f"Topics: {', '.join(meta.get('topics') or []) or 'n/a'}"
                    ),
                    file_name="repository.md",
                    document_type="markdown",
                    source="github",
                    location=meta.get("html_url"),
                    timestamp=meta.get("pushed_at"),
                    metadata={"repository": repository},
                )
            )
            branch = meta.get("default_branch", "main")
            tree = (
                await client.get(f"/repos/{repository}/git/trees/{branch}?recursive=1")
            ).json()
            blobs = [
                node
                for node in tree.get("tree", [])
                if node.get("type") == "blob"
                and node["path"].lower().endswith(RELEVANT_SUFFIXES)
            ][:MAX_FILES]
            for node in blobs:
                blob = (
                    await client.get(f"/repos/{repository}/git/blobs/{node['sha']}")
                ).json()
                if blob.get("encoding") != "base64":
                    continue
                text = base64.b64decode(blob["content"]).decode("utf-8", "replace")
                if not text.strip():
                    continue
                documents.append(
                    SourceDocument(
                        content=text,
                        file_name=node["path"],
                        document_type="code",
                        source="github",
                        location=f"https://github.com/{repository}/blob/{branch}/{node['path']}",
                        metadata={"repository": repository},
                    )
                )
        return documents
