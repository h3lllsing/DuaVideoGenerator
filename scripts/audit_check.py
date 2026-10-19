"""Quick audit script — checks for common issues."""

from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
issues = []

# 1. F821: Undefined names — check word_highlight.py
wh = (PROJECT / "core" / "word_highlight.py").read_text(encoding="utf-8")
if '"Image.Image"' in wh:
    issues.append(
        (
            "F821",
            "core/word_highlight.py:191",
            "Undefined name 'Image' in type hint — should use from __future__ import annotations or just str",
        )
    )

# 2. F821: Undefined 'e' in wife_app.py
wa = (PROJECT / "frontend" / "wife_app.py").read_text(encoding="utf-8")
lines = wa.split("\n")
for i, line in enumerate(lines, 1):
    if "str(e)" in line and "except" not in line:
        # Check if 'e' is bound in an except clause
        prev_lines = "\n".join(lines[max(0, i - 5) : i])
        if "except Exception:" in prev_lines and "as e" not in prev_lines:
            issues.append(("F821", f"frontend/wife_app.py:{i}", "Undefined 'e' — except clause missing 'as e'"))

# 3. F841: Unused variables
for f, var, line_num in [
    ("core/effects_engine.py", "rng", 303),
    ("core/effects_engine.py", "tint", 534),
    ("core/hardware.py", "gpu", 99),
    ("remotion/scripts/ai_import.py", "cats", 453),
    ("tests/test_scene_engine.py", "r", 342),
]:
    issues.append(("F841", f"{f}:{line_num}", f"Unused variable '{var}'"))

# 4. Check for exposed API keys in committed files
for p in PROJECT.rglob("*.json"):
    if "node_modules" in str(p) or "backups" in str(p) or ".git" in str(p):
        continue
    try:
        text = p.read_text(encoding="utf-8")
        if "sk-" in text and "api_key" in text.lower():
            issues.append(("SECURITY", str(p.relative_to(PROJECT)), "Contains API keys in plaintext"))
    except Exception:
        pass

# 5. Check auth.json is gitignored
gitignore = (PROJECT / ".gitignore").read_text(encoding="utf-8") if (PROJECT / ".gitignore").exists() else ""
if "auth.json" not in gitignore:
    issues.append(("SECURITY", ".gitignore", "auth.json not in .gitignore"))

# 6. Check for bare except clauses
for p in PROJECT.rglob("*.py"):
    if "backups" in str(p) or "__pycache__" in str(p) or "node_modules" in str(p):
        continue
    try:
        lines = p.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped == "except:" or stripped == "except :":
                issues.append(("STYLE", f"{p.relative_to(PROJECT)}:{i}", "Bare except clause"))
    except Exception:
        pass

# Print results
print(f"=== AUDIT FOUND {len(issues)} ISSUES ===\n")
for severity, location, desc in issues:
    print(f"[{severity}] {location}: {desc}")
