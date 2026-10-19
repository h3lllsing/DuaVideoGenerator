"""Security Audit Script

Supports text (default), JSON, and SARIF output formats.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

# Rule definitions for structured output
RULES = {
    "path-traversal": {"severity": "critical", "message": "Path traversal vulnerability: {path}"},
    "auth-token-missing": {"severity": "medium", "message": "Auth token file not found"},
    "auth-token-weak": {"severity": "high", "message": "Auth token appears weak or predictable"},
    "gitignore-missing": {"severity": "low", "message": ".gitignore file not found"},
    "gitignore-unprotected": {"severity": "medium", "message": ".gitignore missing pattern: {pattern}"},
    "header-missing": {"severity": "medium", "message": "Missing security header: {header}"},
    "server-not-found": {"severity": "medium", "message": "server.js not found"},
    "validation-missing": {"severity": "high", "message": "Missing input validation: {check}"},
    "render-not-found": {"severity": "medium", "message": "render.js not found"},
    "rate-limiter-missing": {"severity": "high", "message": "Rate limiter missing"},
    "html-escaping-missing": {"severity": "high", "message": "HTML escaping missing in client code"},
    "app-not-found": {"severity": "medium", "message": "app.js not found"},
}


def _make_finding(rule_id, file=None, line=None, severity=None, message=None):
    """Create a structured finding dict."""
    rule = RULES.get(rule_id, {})
    return {
        "ruleId": rule_id,
        "severity": severity or rule.get("severity", "low"),
        "message": message or rule.get("message", rule_id),
        "file": file,
        "line": line,
    }


def run_audit():
    """Run all security checks and return findings list."""
    findings = []

    # Test 1: Path traversal
    test_paths = [
        "../../etc/passwd",
        "../../../windows/system32/config/sam",
        "/etc/shadow",
    ]
    for p in test_paths:
        full = (PROJECT / p).resolve()
        safe = full.is_relative_to(PROJECT)
        if not safe:
            findings.append(
                _make_finding(
                    "path-traversal",
                    file=str(full),
                    message=f"Path traversal allowed: {p}",
                )
            )

    # Test 2: Auth token
    auth_path = PROJECT / "remotion/dashboard/auth.json"
    if auth_path.exists():
        with open(auth_path) as f:
            data = json.load(f)
        token = data.get("token", "")
        if len(token) < 16:
            findings.append(
                _make_finding(
                    "auth-token-weak",
                    file=str(auth_path),
                    message=f"Auth token too short: {len(token)} chars",
                )
            )
    else:
        findings.append(
            _make_finding(
                "auth-token-missing",
                file=str(auth_path),
            )
        )

    # Test 3: .gitignore
    gitignore_path = PROJECT / ".gitignore"
    if gitignore_path.exists():
        gitignore = gitignore_path.read_text()
        secrets = ["client_secret.json", "auth.json", "*.pem", "*.key"]
        for s in secrets:
            if s not in gitignore:
                findings.append(
                    _make_finding(
                        "gitignore-unprotected",
                        file=str(gitignore_path),
                        message=f"Gitignore missing pattern: {s}",
                    )
                )
    else:
        findings.append(
            _make_finding(
                "gitignore-missing",
                file=str(gitignore_path),
            )
        )

    # Test 4: Security headers
    server_path = PROJECT / "remotion/dashboard/server.js"
    if server_path.exists():
        server = server_path.read_text()
        headers = ["X-Content-Type-Options", "X-Frame-Options", "X-XSS-Protection", "Referrer-Policy"]
        for h in headers:
            if h not in server:
                findings.append(
                    _make_finding(
                        "header-missing",
                        file=str(server_path),
                        message=f"Missing security header: {h}",
                    )
                )
    else:
        findings.append(
            _make_finding(
                "server-not-found",
                file=str(server_path),
            )
        )

    # Test 5: Input validation
    render_path = PROJECT / "remotion/dashboard/routes/render.js"
    if render_path.exists():
        render = render_path.read_text(encoding="utf-8", errors="replace")
        checks = ["path.basename", "startsWith(OUT)", "escapeHtml", "sanitizeTts"]
        for c in checks:
            if c not in render:
                findings.append(
                    _make_finding(
                        "validation-missing",
                        file=str(render_path),
                        message=f"Missing validation: {c}",
                    )
                )
    else:
        findings.append(
            _make_finding(
                "render-not-found",
                file=str(render_path),
            )
        )

    # Test 6: Rate limiting
    if server_path.exists():
        server = server_path.read_text(encoding="utf-8", errors="replace")
        if "checkRateLimit" not in server:
            findings.append(
                _make_finding(
                    "rate-limiter-missing",
                    file=str(server_path),
                )
            )

    # Test 7: XSS protection
    app_path = PROJECT / "remotion/dashboard/public/app.js"
    if app_path.exists():
        app = app_path.read_text(encoding="utf-8", errors="replace")
        if "escapeHtml" not in app and "escHtml" not in app:
            findings.append(
                _make_finding(
                    "html-escaping-missing",
                    file=str(app_path),
                )
            )
    else:
        findings.append(
            _make_finding(
                "app-not-found",
                file=str(app_path),
            )
        )

    return findings


def _build_summary(findings):
    """Build severity summary from findings."""
    summary = {"total": len(findings), "critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.get("severity", "low")
        if sev in summary:
            summary[sev] += 1
    return summary


def output_text(findings):
    """Print findings as human-readable text."""
    print("=== Security Audit ===")
    print(f"Project: {PROJECT}")
    print()
    if findings:
        print(f"Findings: {len(findings)} issues found")
        for f in findings:
            loc = ""
            if f["file"]:
                loc = f" in {f['file']}"
            print(f"  [{f['severity'].upper()}] {f['message']}{loc}")
    else:
        print("No issues found - all checks passed!")
    print()
    summary = _build_summary(findings)
    print(
        f"Summary: {summary['total']} total | {summary['critical']} critical | "
        f"{summary['high']} high | {summary['medium']} medium | {summary['low']} low"
    )


def output_json(findings):
    """Output findings as JSON."""
    result = {
        "findings": findings,
        "summary": _build_summary(findings),
    }
    print(json.dumps(result, indent=2))


def output_sarif(findings):
    """Output findings in SARIF 2.1.0 format."""
    rules = []
    for rule_id, rule_def in RULES.items():
        rules.append(
            {
                "id": rule_id,
                "shortDescription": {"text": rule_def.get("message", rule_id)},
                "defaultConfiguration": {
                    "level": {
                        "critical": "error",
                        "high": "error",
                        "medium": "warning",
                        "low": "note",
                    }.get(rule_def.get("severity", "low"), "warning"),
                },
            }
        )

    results = []
    for f in findings:
        sarif_level = {
            "critical": "error",
            "high": "error",
            "medium": "warning",
            "low": "note",
        }.get(f.get("severity", "low"), "warning")
        result_entry = {
            "ruleId": f["ruleId"],
            "level": sarif_level,
            "message": {"text": f["message"]},
        }
        if f.get("file"):
            loc = {
                "physicalLocation": {
                    "artifactLocation": {"uri": f["file"], "uriBaseId": "%SRCROOT%"},
                }
            }
            if f.get("line"):
                loc["physicalLocation"]["region"] = {"startLine": f["line"]}
            result_entry["locations"] = [{"location": loc}]
        results.append(result_entry)

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "dua-security-audit",
                        "version": "1.0.0",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    print(json.dumps(sarif, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Security Audit Script")
    parser.add_argument(
        "--format",
        choices=["text", "json", "sarif"],
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    findings = run_audit()

    if args.format == "json":
        output_json(findings)
    elif args.format == "sarif":
        output_sarif(findings)
    else:
        output_text(findings)

    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
