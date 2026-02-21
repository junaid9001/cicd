import json
import re
from dataclasses import dataclass
from typing import Dict, List, Pattern, Tuple

from .schemas import VulnFinding, VulnScanResponse


@dataclass
class ScanRule:
    rule_id: str
    severity: str
    category: str
    title: str
    pattern: Pattern[str]
    recommendation: str
    path_contains: Tuple[str, ...] = ()


RULES: List[ScanRule] = [
    ScanRule(
        rule_id="secret.aws_access_key",
        severity="critical",
        category="secrets",
        title="Potential AWS access key exposed",
        pattern=re.compile(r"AKIA[0-9A-Z]{16}"),
        recommendation="Remove hardcoded keys and rotate credentials immediately.",
    ),
    ScanRule(
        rule_id="secret.generic_token",
        severity="high",
        category="secrets",
        title="Potential hardcoded API token or secret",
        pattern=re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
        recommendation="Move secrets to environment variables or a secrets manager.",
    ),
    ScanRule(
        rule_id="python.eval",
        severity="high",
        category="code_injection",
        title="Use of eval()",
        pattern=re.compile(r"(?<!\w)eval\s*\("),
        recommendation="Avoid eval on dynamic input. Use safe parsing or strict whitelists.",
        path_contains=(".py",),
    ),
    ScanRule(
        rule_id="python.exec",
        severity="high",
        category="code_injection",
        title="Use of exec()",
        pattern=re.compile(r"(?<!\w)exec\s*\("),
        recommendation="Avoid exec on dynamic input. Refactor to explicit control flow.",
        path_contains=(".py",),
    ),
    ScanRule(
        rule_id="python.shell_true",
        severity="high",
        category="command_injection",
        title="subprocess with shell=True",
        pattern=re.compile(r"subprocess\.(run|Popen|call)\(.*shell\s*=\s*True"),
        recommendation="Use list-based command args and avoid shell=True.",
        path_contains=(".py",),
    ),
    ScanRule(
        rule_id="js.eval",
        severity="high",
        category="code_injection",
        title="Use of eval() in JS/TS",
        pattern=re.compile(r"(?<!\w)eval\s*\("),
        recommendation="Remove eval usage and use safe alternatives.",
        path_contains=(".js", ".ts", ".jsx", ".tsx"),
    ),
    ScanRule(
        rule_id="tls.disabled",
        severity="high",
        category="crypto",
        title="TLS certificate validation appears disabled",
        pattern=re.compile(r"verify\s*=\s*False|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|rejectUnauthorized\s*:\s*false"),
        recommendation="Enable TLS verification and valid certificate checks in all environments.",
    ),
    ScanRule(
        rule_id="debug.enabled",
        severity="medium",
        category="misconfiguration",
        title="Debug mode enabled",
        pattern=re.compile(r"DEBUG\s*=\s*True|app\.run\(.*debug\s*=\s*True"),
        recommendation="Disable debug mode in production configuration.",
    ),
    ScanRule(
        rule_id="sql.concat",
        severity="medium",
        category="sqli",
        title="Potential SQL query string concatenation",
        pattern=re.compile(r"(?i)(SELECT|UPDATE|INSERT|DELETE).*(\+|\%s|\{.*\}).*(FROM|INTO|SET)"),
        recommendation="Use parameterized queries or ORM prepared statements.",
    ),
]


def _line_number(content: str, pos: int) -> int:
    return content.count("\n", 0, pos) + 1


def _snippet(line: str) -> str:
    clean = line.strip()
    return clean[:180]


def _path_allowed(path: str, allowed_parts: Tuple[str, ...]) -> bool:
    if not allowed_parts:
        return True
    lower = path.lower()
    return any(lower.endswith(part) for part in allowed_parts)


def _dependency_findings(path: str, content: str) -> List[VulnFinding]:
    findings: List[VulnFinding] = []
    lower = path.lower()
    if lower.endswith("requirements.txt"):
        for i, raw in enumerate(content.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "==" not in line:
                findings.append(
                    VulnFinding(
                        rule_id="deps.unpinned.python",
                        severity="low",
                        category="dependency_hygiene",
                        title="Unpinned Python dependency",
                        path=path,
                        line=i,
                        snippet=_snippet(raw),
                        recommendation="Pin exact versions (e.g., package==1.2.3) for reproducible builds.",
                    )
                )
    if lower.endswith("package.json"):
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return findings
        for section in ("dependencies", "devDependencies"):
            deps = data.get(section, {})
            if not isinstance(deps, dict):
                continue
            for pkg, version in deps.items():
                v = str(version).strip().lower()
                if v in {"latest", "*"} or v.startswith("github:"):
                    findings.append(
                        VulnFinding(
                            rule_id="deps.unpinned.node",
                            severity="low",
                            category="dependency_hygiene",
                            title="Non-deterministic Node dependency version",
                            path=path,
                            line=1,
                            snippet=f"{pkg}: {version}",
                            recommendation="Pin dependency to a stable semver range or exact version.",
                        )
                    )
    return findings


def scan_repository(repository: str, branch: str, files: Dict[str, str]) -> VulnScanResponse:
    findings: List[VulnFinding] = []
    for path, content in files.items():
        lines = content.splitlines()
        for rule in RULES:
            if not _path_allowed(path, rule.path_contains):
                continue
            for match in rule.pattern.finditer(content):
                line_no = _line_number(content, match.start())
                line_text = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
                findings.append(
                    VulnFinding(
                        rule_id=rule.rule_id,
                        severity=rule.severity,  # type: ignore[arg-type]
                        category=rule.category,
                        title=rule.title,
                        path=path,
                        line=line_no,
                        snippet=_snippet(line_text),
                        recommendation=rule.recommendation,
                    )
                )
                if len(findings) >= 300:
                    break
            if len(findings) >= 300:
                break
        findings.extend(_dependency_findings(path, content))
        if len(findings) >= 300:
            break

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for item in findings:
        counts[item.severity] += 1

    return VulnScanResponse(
        repository=repository,
        branch=branch,
        scanned_files=len(files),
        severity_counts=counts,
        findings=findings,
    )
