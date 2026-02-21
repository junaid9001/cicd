import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests


class GitHubError(RuntimeError):
    pass


REPO_REGEX = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


@dataclass
class RepoData:
    owner: str
    repo: str
    default_branch: str
    tree_paths: List[str]
    file_contents: Dict[str, str]

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_repo_url(url: str) -> Tuple[str, str]:
    match = REPO_REGEX.match(url.strip())
    if not match:
        raise GitHubError("Provide a valid GitHub repository URL like https://github.com/org/repo")
    return match.group("owner"), match.group("repo")


def _headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "repo2ci-generator",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str) -> Dict[str, object]:
    resp = requests.get(url, headers=_headers(), timeout=30)
    if resp.status_code >= 400:
        try:
            payload = resp.json()
            msg = payload.get("message", "GitHub request failed")
        except ValueError:
            msg = resp.text
        raise GitHubError(f"GitHub API error ({resp.status_code}): {msg}")
    return resp.json()


def fetch_repo_data(repo_url: str, branch: Optional[str]) -> RepoData:
    owner, repo = parse_repo_url(repo_url)

    repo_meta = _get_json(f"https://api.github.com/repos/{owner}/{repo}")
    default_branch = str(repo_meta.get("default_branch") or "main")
    selected_branch = branch or default_branch

    tree_payload = _get_json(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{selected_branch}?recursive=1"
    )
    raw_tree = tree_payload.get("tree", [])
    if not isinstance(raw_tree, list):
        raise GitHubError("Unable to read repository tree from GitHub.")

    paths: List[str] = []
    blobs: List[str] = []
    for item in raw_tree:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        path = item.get("path")
        if not isinstance(path, str):
            continue
        paths.append(path)
        if item_type == "blob":
            blobs.append(path)

    target_files = [
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "go.mod",
        "Cargo.toml",
        "composer.json",
        "Gemfile",
    ]

    content_map: Dict[str, str] = {}
    blobs_set = set(blobs)
    for name in target_files:
        matches = [p for p in blobs if p.endswith(name)]
        if not matches:
            continue
        # Read only closest-to-root file first for speed.
        target_path = sorted(matches, key=lambda p: p.count("/"))[0]
        if target_path not in blobs_set:
            continue
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{selected_branch}/{target_path}"
        resp = requests.get(raw_url, headers=_headers(), timeout=30)
        if resp.status_code < 400:
            content_map[target_path] = resp.text[:100_000]

    return RepoData(
        owner=owner,
        repo=repo,
        default_branch=selected_branch,
        tree_paths=paths,
        file_contents=content_map,
    )
