import json
from collections import Counter
from typing import Dict, List, Set

from .github_client import RepoData
from .schemas import TechProfile


EXT_LANGUAGE = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": ".NET",
    ".c": "C/C++",
    ".cpp": "C/C++",
    ".h": "C/C++",
    ".hpp": "C/C++",
    ".swift": "Swift",
}


def _parse_package_json(content: str) -> Set[str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return set()
    deps = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        values = data.get(key, {})
        if isinstance(values, dict):
            deps.update({str(k).lower() for k in values.keys()})
    return deps


def _parse_requirements(content: str) -> Set[str]:
    deps: Set[str] = set()
    for line in content.splitlines():
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        token = line.split("==")[0].split(">=")[0].split("[")[0].strip()
        if token:
            deps.add(token)
    return deps


def analyze_repo(repo_data: RepoData) -> TechProfile:
    lang_counter: Counter[str] = Counter()
    package_managers: Set[str] = set()
    frameworks: Set[str] = set()
    test_hints: Set[str] = set()

    for path in repo_data.tree_paths:
        lower = path.lower()
        for ext, lang in EXT_LANGUAGE.items():
            if lower.endswith(ext):
                lang_counter[lang] += 1
                break

        if lower.endswith("dockerfile"):
            pass
        if lower.endswith("package.json"):
            package_managers.add("npm/yarn/pnpm")
        if lower.endswith("requirements.txt") or lower.endswith("pyproject.toml") or lower.endswith("pipfile"):
            package_managers.add("pip/poetry")
        if lower.endswith("pom.xml") or lower.endswith("build.gradle") or lower.endswith("build.gradle.kts"):
            package_managers.add("maven/gradle")
        if lower.endswith("go.mod"):
            package_managers.add("go modules")
        if lower.endswith("cargo.toml"):
            package_managers.add("cargo")

    file_contents: Dict[str, str] = repo_data.file_contents
    for path, content in file_contents.items():
        lower = path.lower()
        if lower.endswith("package.json"):
            deps = _parse_package_json(content)
            if "next" in deps:
                frameworks.add("Next.js")
            if "react" in deps:
                frameworks.add("React")
            if "vue" in deps:
                frameworks.add("Vue")
            if "nestjs" in deps:
                frameworks.add("NestJS")
            if "express" in deps:
                frameworks.add("Express")
            if "jest" in deps or "vitest" in deps:
                test_hints.add("npm test")

        if lower.endswith("requirements.txt"):
            deps = _parse_requirements(content)
            if "django" in deps:
                frameworks.add("Django")
            if "flask" in deps:
                frameworks.add("Flask")
            if "fastapi" in deps:
                frameworks.add("FastAPI")
            if "pytest" in deps:
                test_hints.add("pytest")

        if lower.endswith("pyproject.toml"):
            text = content.lower()
            if "fastapi" in text:
                frameworks.add("FastAPI")
            if "django" in text:
                frameworks.add("Django")
            if "flask" in text:
                frameworks.add("Flask")
            if "pytest" in text:
                test_hints.add("pytest")

        if lower.endswith("pom.xml") or lower.endswith("build.gradle") or lower.endswith("build.gradle.kts"):
            text = content.lower()
            if "spring-boot" in text:
                frameworks.add("Spring Boot")
            if "junit" in text:
                test_hints.add("mvn test")

    has_dockerfile = any(p.lower().endswith("dockerfile") for p in repo_data.tree_paths)
    languages = [lang for lang, _ in lang_counter.most_common()] or ["Unknown"]
    primary = languages[0]

    if not test_hints:
        if primary in ("JavaScript", "TypeScript"):
            test_hints.add("npm test")
        elif primary == "Python":
            test_hints.add("pytest")
        elif primary == "Java":
            test_hints.add("mvn test")
        elif primary == "Go":
            test_hints.add("go test ./...")
        elif primary == "Rust":
            test_hints.add("cargo test")

    return TechProfile(
        primary_language=primary,
        languages=languages,
        frameworks=sorted(frameworks),
        package_managers=sorted(package_managers),
        has_dockerfile=has_dockerfile,
        test_hints=sorted(test_hints),
    )
