#!/usr/bin/env python3
"""Alignment check for todo/问题清单.md after 2026-04-16 cleanup.

Per plans/2026-04-arch10-residual.yaml T5. Run as a plain script:
    python tests/test_issue_list_alignment.py

Exits 0 on alignment, non-zero with error list otherwise.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1] / "todo"


def section(text: str, start: str, end_prefixes: list[str]) -> str | None:
    if start not in text:
        return None
    tail = text.split(start, 1)[1]
    for end in end_prefixes:
        if end in tail:
            tail = tail.split(end, 1)[0]
            break
    return tail


def main() -> int:
    doc_path = ROOT / "问题清单.md"
    full_path = ROOT / "问题清单-full.md"

    if not doc_path.exists():
        print(f"FAIL: missing {doc_path}")
        return 1
    if not full_path.exists():
        print(f"FAIL: missing {full_path}")
        return 1

    doc = doc_path.read_text(encoding="utf-8")
    full = full_path.read_text(encoding="utf-8")

    errors: list[str] = []

    # 1. Required headers must exist
    for header in ("## 一、核心待解决", "## 二、次级待解决"):
        if header not in doc:
            errors.append(f"missing header: {header}")

    # 2/3. Parse sections strictly — split failure is an error, not a silent empty
    core = section(doc, "## 一、核心待解决", ["## 二"])
    sec = section(doc, "## 二、次级待解决", ["## 三"])
    if core is None:
        errors.append("core section unparseable")
    if sec is None:
        errors.append("secondary section unparseable")

    # 2. Removed from core
    if core is not None:
        for tid in ("ARCH-4", "FIX-13"):
            if tid in core:
                errors.append(f"{tid} still in core section")

    # 3. Removed from secondary
    if sec is not None:
        for tid in ("FIX-22", "FIX-25", "FIX-26"):
            if tid in sec:
                errors.append(f"{tid} still in secondary section")

    # 4. ARCH-10 must not be marked P0 anymore
    if re.search(r"###\s*ARCH-10[^\n]*P0", doc):
        errors.append("ARCH-10 still marked as P0 in main list")

    # 5. Full archive section must list the closed ids
    if not re.search(r"已验证|已实施", full):
        errors.append("full archive missing 已验证/已实施 section")
    else:
        idx = min(
            i for i in (full.find("已验证"), full.find("已实施")) if i >= 0
        )
        archived_section = full[idx:]
        for tid in ("ARCH-4", "FIX-13", "FIX-22", "FIX-25", "FIX-26", "ARCH-10"):
            if tid not in archived_section:
                errors.append(f"{tid} missing from full archive section")

    # 6. Main list 已移入 Full section must reference the closed ids
    moved_section = section(doc, "## 四、已移入 Full", ["## 五"]) or section(
        doc, "已移入 Full", []
    )
    if moved_section is None:
        errors.append("main list missing 已移入 Full section")
    else:
        for tid in ("ARCH-4", "FIX-13", "FIX-22", "FIX-25", "FIX-26"):
            if tid not in moved_section:
                errors.append(f"{tid} not listed in 已移入 Full section")

    # 7. Table column heuristic — catch wildly-broken tables
    for name, text in (("main", doc), ("full", full)):
        rows = [
            line
            for line in text.splitlines()
            if line.strip().startswith("|") and line.strip().endswith("|")
        ]
        col_counts = {line.count("|") for line in rows}
        if col_counts and len(col_counts) > 3:
            errors.append(
                f"{name} markdown tables look broken (column counts: "
                f"{sorted(col_counts)[:5]})"
            )

    # 8. Internal link targets must exist
    for name, text in (("main", doc), ("full", full)):
        for m in re.finditer(r"\[[^\]]+\]\(([^)]+\.md)\)", text):
            target = m.group(1)
            if target.startswith("http"):
                continue
            path = (ROOT / target).resolve()
            if not path.exists():
                errors.append(f"{name} broken link: {target}")

    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("issue list alignment OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
