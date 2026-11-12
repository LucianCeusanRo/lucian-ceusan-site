#!/usr/bin/env python3
"""Check that local href/src in index.html exist, plus required site files.

CV PDFs are added at deploy time (see .gitignore) and are skipped here.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_PREFIXES = ("http://", "https://", "mailto:", "tel:", "//", "data:", "javascript:")
SKIP_NAMES = re.compile(r"Lucian_Ceusan_CV.*\.pdf$", re.I)
# Portrait is swapped in only if the file is present (JS Image.onload). Not in the repo yet.
OPTIONAL_LOCAL = {"img/lucian.webp"}
REQUIRED = [
    "index.html",
    "favicon.svg",
    "sitemap.xml",
    "robots.txt",
    "llms.txt",
    "vercel.json",
    "og.png",
]


def is_skipped(url: str) -> bool:
    u = (url or "").strip()
    if not u or u.startswith(SKIP_PREFIXES) or u.startswith("#"):
        return True
    path = u.split("?")[0].split("#")[0]
    return bool(SKIP_NAMES.search(path))


def resolve(url: str) -> Path:
    path = url.split("?")[0].split("#")[0]
    if path.startswith("/"):
        path = path[1:]
    return ROOT / path


def main() -> int:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", html, re.I)
    missing: list[str] = []
    checked = 0
    for url in refs:
        if is_skipped(url):
            continue
        rel = url.split("?")[0].split("#")[0].lstrip("/")
        if rel in OPTIONAL_LOCAL and not resolve(url).exists():
            continue
        checked += 1
        if not resolve(url).exists():
            missing.append(url)
    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            missing.append(rel)
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    if "lucian-ceusan.vercel.app" not in sitemap:
        print("sitemap.xml does not mention lucian-ceusan.vercel.app")
        return 1
    print(f"checked {checked} local refs and {len(REQUIRED)} required files")
    if missing:
        print("MISSING:")
        for item in missing:
            print(" ", item)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
