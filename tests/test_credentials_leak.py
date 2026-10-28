"""
Security Test Suite: Credential Leak Scanner
Verifies that no private bot tokens, API hashes, or sensitive credentials
are committed or present in files staged for GitHub.
"""

import os
import re
import sys
from pathlib import Path

# Sensitive credentials that must NEVER appear in public code
FORBIDDEN_STRINGS = [
    "8544932366:AAGvtPGsNR3H3G3uu6t34pxH2APu6v8HUQI",
    "6646b1e76da41504f226eec967a46b82",
]

# Regex pattern for general Telegram bot tokens (e.g. 123456789:ABCdefGhIjk...)
BOT_TOKEN_PATTERN = re.compile(r"\b\d{8,11}:[A-Za-z0-9_-]{35}\b")

# Files and directories allowed to be excluded from this check
IGNORED_DIRS = {
    ".git",
    "__pycache__",
    "downloads",
    "temp",
    "extracted",
    ".pytest_cache",
    "venv",
    ".venv",
}

IGNORED_FILES = {
    ".env",                 # Local environment file (protected by .gitignore)
    "test_credentials_leak.py", # This scanner itself
}


def check_gitignore():
    """Verify that .gitignore exists and contains critical ignore rules."""
    root = Path(__file__).resolve().parent.parent
    gitignore_path = root / ".gitignore"
    if not gitignore_path.exists():
        print("[FAIL] .gitignore file does not exist!")
        return False
    
    content = gitignore_path.read_text(encoding="utf-8")
    required_ignores = [".env", "*.session", "*.ipynb"]
    missing = [req for req in required_ignores if req not in content]
    
    if missing:
        print(f"[FAIL] .gitignore is missing critical patterns: {missing}")
        return False
    
    print("[PASS] .gitignore correctly ignores sensitive files.")
    return True


def is_git_ignored(path: Path) -> bool:
    """Uses git check-ignore to check if a file is ignored by .gitignore."""
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            capture_output=True
        )
        return proc.returncode == 0
    except Exception:
        return False


def scan_files_for_leaks():
    """Recursively scan codebase for forbidden strings and token regex in all git-tracked files."""
    root = Path(__file__).resolve().parent.parent
    violations = []

    for path in root.rglob("*"):
        if path.is_dir():
            continue
        
        # Skip git internal objects and this test file
        parts = set(path.parts)
        if ".git" in parts or path.name == "test_credentials_leak.py":
            continue

        # If file is ignored by .gitignore, verify it's safe from git
        if is_git_ignored(path):
            continue
        
        # Read file content
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        
        # Check forbidden exact strings
        for forbidden in FORBIDDEN_STRINGS:
            if forbidden in content:
                violations.append((path, f"Contains forbidden private credential: {forbidden[:10]}..."))

        # Check bot token pattern
        match = BOT_TOKEN_PATTERN.search(content)
        if match:
            violations.append((path, f"Contains Telegram bot token pattern: {match.group(0)[:10]}..."))

    return violations


def main():
    print("=" * 60)
    print("Running Security & Credential Leakage Verification...")
    print("=" * 60)

    gitignore_ok = check_gitignore()
    leaks = scan_files_for_leaks()

    if leaks:
        print("\n[CRITICAL ERROR] Credentials found in files to be pushed to GitHub:")
        for path, reason in leaks:
            print(f"  - {path}: {reason}")
        print("\nFix these violations before pushing to Git!")
        sys.exit(1)

    if not gitignore_ok:
        sys.exit(1)

    print("\n[SUCCESS] No credentials leaked! Code is clean and safe for GitHub.")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
