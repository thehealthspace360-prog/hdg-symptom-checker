#!/usr/bin/env python3
"""
HDG Article Index Updater / Validator
=====================================

Purpose
-------
Semi-automatic maintenance for HDG_Public_Article_Index.txt.

It:
1. validates current article metadata;
2. compares the public index with the HDG sitemap;
3. flags new/unindexed URLs;
4. flags indexed URLs no longer present in the sitemap;
5. generates REVIEW stubs for new URLs;
6. never silently changes clinical metadata or publishes a new live index.

Standard-library only: no pip install required.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_INDEX = "HDG_Public_Article_Index.txt"
DEFAULT_SITEMAP = "https://www.healthdecodedguide.com/sitemap.xml"

REQUIRED_FIELDS = ("TITLE", "LANGUAGE", "CATEGORY", "EMERGENCY", "URL", "KEYWORDS")
VALID_LANGUAGES = {"English", "Pidgin"}
VALID_EMERGENCY = {"YES", "NO"}

# Pages that are public website pages but are usually not medical-library article records.
DEFAULT_NON_ARTICLE_PATH_PARTS = {
    "/about", "/contact", "/privacy", "/privacy-policy", "/terms", "/terms-of-use",
    "/cookie", "/cookies", "/cookie-policy", "/faq", "/faqs", "/our-story",
    "/editorial-policy", "/why-trust", "/physician-reviewed", "/evidence-based",
    "/partner-with-us", "/report-an-error", "/disclaimer", "/medical-disclaimer",
    "/search", "/blog", "/home"
}

PIDGIN_URL_MARKERS = ("pidgin-english", "/pidgin/", "-pidgin")
PIDGIN_TITLE_MARKERS = (
    " pikin", " wetin", " no dey", " dey ", " wahala", " no fit ",
    " for pikin", " blood for urine", " problem for pikin"
)

# Conservative category checks. These are REVIEW flags, never automatic edits.
CATEGORY_HINTS = [
    (("pcos", "polycystic ovary", "fibroid", "adenomyosis", "endometriosis", "menopause", "vaginal"),
     "Women's Health"),
    (("erectile", "prostate", "bph", "testicular", "testicle", "varicocele", "hydrocele", "spermatocele"),
     "Men's Health"),
    (("depression", "anxiety", "panic attack", "ptsd", "behavioral addiction", "anger problems"),
     "Mental Health"),
    (("asthma", "copd", "wheezing", "shortness of breath", "breathing difficulty"),
     "Respiratory / Allergy"),
]

@dataclass
class Article:
    number: str
    fields: dict[str, str]
    start_line: int

    @property
    def url(self) -> str:
        return self.fields.get("URL", "")

    @property
    def title(self) -> str:
        return self.fields.get("TITLE", "")


def norm_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    p = urllib.parse.urlsplit(url)
    path = re.sub(r"/+$", "", p.path) or "/"
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))


def slug_to_title(url: str) -> str:
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    slug = path.split("/")[-1]
    slug = re.sub(r"^\d+_", "", slug)
    words = re.sub(r"[-_]+", " ", slug).strip()
    return " ".join(w.capitalize() if not w.isupper() else w for w in words.split())


def infer_language_from_url_title(url: str, title: str) -> str:
    low = (url + " " + title).lower()
    if any(marker in low for marker in PIDGIN_URL_MARKERS):
        return "Pidgin"
    if any(marker in (" " + title.lower()) for marker in PIDGIN_TITLE_MARKERS):
        return "Pidgin"
    return "REVIEW"


def is_probable_non_article(url: str, config: dict) -> bool:
    path = urllib.parse.urlsplit(url).path.lower().rstrip("/")
    parts = set(DEFAULT_NON_ARTICLE_PATH_PARTS)
    parts.update(x.lower().rstrip("/") for x in config.get("non_article_path_parts", []))
    return any(path == p or path.startswith(p + "/") for p in parts)


def parse_index(path: Path) -> list[Article]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    articles: list[Article] = []
    current_number = None
    current_fields: dict[str, str] = {}
    start_line = 0

    def flush():
        nonlocal current_number, current_fields, start_line
        if current_number is not None:
            articles.append(Article(current_number, dict(current_fields), start_line))
        current_number = None
        current_fields = {}
        start_line = 0

    for i, line in enumerate(lines, start=1):
        m = re.match(r"^ARTICLE\s+(\d+)\s*$", line.strip(), re.I)
        if m:
            flush()
            current_number = m.group(1).strip()
            start_line = i
            continue
        if current_number is not None and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().upper()
            if key == "EMERGENCY FLAG":
                key = "EMERGENCY"
            if key in REQUIRED_FIELDS:
                current_fields[key] = value.strip()
    flush()
    return articles


def validate_metadata(articles: list[Article]) -> list[dict]:
    issues: list[dict] = []
    seen_urls: dict[str, Article] = {}
    seen_numbers: dict[str, Article] = {}

    for a in articles:
        def issue(level: str, code: str, message: str):
            issues.append({
                "level": level,
                "code": code,
                "article": a.number,
                "title": a.title,
                "url": a.url,
                "line": a.start_line,
                "message": message,
            })

        for f in REQUIRED_FIELDS:
            if not a.fields.get(f, "").strip():
                issue("ERROR", "MISSING_FIELD", f"Missing {f}.")

        if a.fields.get("LANGUAGE") and a.fields["LANGUAGE"] not in VALID_LANGUAGES:
            issue("ERROR", "BAD_LANGUAGE", f"LANGUAGE is {a.fields['LANGUAGE']!r}; expected English or Pidgin.")

        if a.fields.get("EMERGENCY") and a.fields["EMERGENCY"].upper() not in VALID_EMERGENCY:
            issue("ERROR", "BAD_EMERGENCY", f"EMERGENCY is {a.fields['EMERGENCY']!r}; expected YES or NO.")

        u = norm_url(a.url)
        if u:
            p = urllib.parse.urlsplit(u)
            if p.scheme not in {"http", "https"} or not p.netloc:
                issue("ERROR", "BAD_URL", "URL is not a valid http/https URL.")
            if u in seen_urls:
                issue("ERROR", "DUPLICATE_URL", f"Duplicate URL also used by ARTICLE {seen_urls[u].number}.")
            else:
                seen_urls[u] = a

        if a.number in seen_numbers:
            issue("ERROR", "DUPLICATE_ARTICLE_NUMBER",
                  f"ARTICLE number duplicated; first seen at line {seen_numbers[a.number].start_line}.")
        else:
            seen_numbers[a.number] = a

        low_url = a.url.lower()
        low_title = " " + a.title.lower()
        if (any(x in low_url for x in PIDGIN_URL_MARKERS)
                or any(x in low_title for x in PIDGIN_TITLE_MARKERS)):
            if a.fields.get("LANGUAGE") != "Pidgin":
                issue("ERROR", "LIKELY_PIDGIN_LANGUAGE_MISMATCH",
                      "URL/title strongly looks Pidgin but LANGUAGE is not Pidgin.")

        title_for_category = a.title.lower()
        category = a.fields.get("CATEGORY", "")
        for cues, expected in CATEGORY_HINTS:
            if any(cue in title_for_category for cue in cues) and category and category != expected:
                # Do not flag emergency/children categories, which can legitimately override topic categories.
                if category not in {"Emergency / First Aid", "Children's Health"}:
                    issue("REVIEW", "CATEGORY_REVIEW",
                          f"Topic suggests {expected!r}, but CATEGORY is {category!r}.")
                break

        # Flag suspiciously thin keywords.
        kws = [x.strip() for x in a.fields.get("KEYWORDS", "").split(";") if x.strip()]
        if len(kws) < 2:
            issue("REVIEW", "THIN_KEYWORDS", "Only one or zero keyword terms; retrieval may be weaker.")

    return issues


def fetch_bytes(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "HDG-Index-Validator/1.0 (+https://www.healthdecodedguide.com)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_sitemap_xml(data: bytes) -> tuple[str, list[str]]:
    root = ET.fromstring(data)
    tag = root.tag.rsplit("}", 1)[-1].lower()
    locs = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1].lower() == "loc" and el.text:
            locs.append(html.unescape(el.text.strip()))
    return tag, locs


def collect_sitemap_urls(sitemap_url: str, max_sitemaps: int = 30) -> set[str]:
    """Supports both urlset and sitemapindex, recursively."""
    queue = [sitemap_url]
    visited = set()
    urls: set[str] = set()

    while queue:
        sm = queue.pop(0)
        if sm in visited:
            continue
        visited.add(sm)
        if len(visited) > max_sitemaps:
            raise RuntimeError(f"Exceeded {max_sitemaps} sitemap files; check sitemap structure.")
        data = fetch_bytes(sm)
        tag, locs = parse_sitemap_xml(data)
        if tag == "sitemapindex":
            queue.extend(locs)
        elif tag == "urlset":
            urls.update(norm_url(x) for x in locs if x)
        else:
            # Some generators use a nonstandard root but still contain URLs.
            for x in locs:
                if x.lower().endswith(".xml"):
                    queue.append(x)
                else:
                    urls.add(norm_url(x))
    return {u for u in urls if u}


def collect_sitemap_urls_from_file(path: Path) -> set[str]:
    data = path.read_bytes()
    tag, locs = parse_sitemap_xml(data)
    if tag == "sitemapindex":
        raise RuntimeError("Local sitemap file is a sitemap index. Use --sitemap URL so child sitemaps can be fetched.")
    return {norm_url(x) for x in locs if x}


def load_config(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(
    out_dir: Path,
    articles: list[Article],
    issues: list[dict],
    new_urls: list[str],
    stale_urls: list[str],
    sitemap_count: int | None,
):
    out_dir.mkdir(parents=True, exist_ok=True)

    errors = [x for x in issues if x["level"] == "ERROR"]
    reviews = [x for x in issues if x["level"] == "REVIEW"]

    md = []
    md.append("# HDG Article Index Validation Report")
    md.append("")
    md.append(f"- Indexed articles: **{len(articles)}**")
    if sitemap_count is not None:
        md.append(f"- Sitemap URLs checked: **{sitemap_count}**")
    md.append(f"- Metadata errors: **{len(errors)}**")
    md.append(f"- Metadata review flags: **{len(reviews)}**")
    md.append(f"- New/unindexed article-like URLs: **{len(new_urls)}**")
    md.append(f"- Indexed URLs absent from sitemap: **{len(stale_urls)}**")
    md.append("")

    if errors:
        md += ["## Errors", ""]
        for x in errors:
            md.append(f"- **{x['code']}** — ARTICLE {x['article']} `{x['title']}` (line {x['line']}): {x['message']}")
        md.append("")

    if reviews:
        md += ["## Review flags", ""]
        for x in reviews:
            md.append(f"- **{x['code']}** — ARTICLE {x['article']} `{x['title']}` (line {x['line']}): {x['message']}")
        md.append("")

    if new_urls:
        md += ["## New / unindexed URLs", ""]
        md += [f"- {u}" for u in new_urls]
        md.append("")

    if stale_urls:
        md += ["## Indexed URLs not found in sitemap", "",
               "These are **review flags only**. Do not delete automatically; redirects or sitemap exclusions can explain them.", ""]
        md += [f"- {u}" for u in stale_urls]
        md.append("")

    md += [
        "## Publishing rule",
        "",
        "**Do not automatically replace the live HDG index from this report.**",
        "Review new articles and any ERROR/REVIEW flags first, especially LANGUAGE, CATEGORY, EMERGENCY and KEYWORDS.",
        "",
    ]
    (out_dir / "HDG_Index_Validation_Report.md").write_text("\n".join(md), encoding="utf-8")

    # Machine-readable output
    payload = {
        "summary": {
            "indexed_articles": len(articles),
            "sitemap_urls": sitemap_count,
            "errors": len(errors),
            "reviews": len(reviews),
            "new_urls": len(new_urls),
            "stale_urls": len(stale_urls),
        },
        "issues": issues,
        "new_urls": new_urls,
        "stale_urls": stale_urls,
    }
    (out_dir / "HDG_Index_Validation_Report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def write_new_article_stubs(out_dir: Path, new_urls: list[str], articles: list[Article]):
    if not new_urls:
        (out_dir / "HDG_New_Article_Stubs.txt").write_text(
            "No new article-like URLs detected.\n", encoding="utf-8"
        )
        return

    nums = []
    for a in articles:
        try:
            nums.append(int(a.number))
        except ValueError:
            pass
    n = max(nums, default=0) + 1

    chunks = [
        "HDG NEW ARTICLE REVIEW STUBS",
        "",
        "These are NOT ready to upload as the live index.",
        "Review LANGUAGE, CATEGORY, EMERGENCY and KEYWORDS before copying into HDG_Public_Article_Index.txt.",
        "",
    ]

    for url in new_urls:
        title = slug_to_title(url)
        language = infer_language_from_url_title(url, title)
        chunks += [
            f"ARTICLE {n}",
            f"TITLE: {title or 'REVIEW'}",
            f"LANGUAGE: {language}",
            "CATEGORY: REVIEW",
            "EMERGENCY: REVIEW",
            f"URL: {url}",
            "KEYWORDS: REVIEW",
            "",
        ]
        n += 1

    (out_dir / "HDG_New_Article_Stubs.txt").write_text("\n".join(chunks), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate HDG public article index and compare it with the HDG sitemap.")
    ap.add_argument("--index", default=DEFAULT_INDEX, help=f"Path to index file (default: {DEFAULT_INDEX})")
    ap.add_argument("--sitemap", default=DEFAULT_SITEMAP, help=f"Sitemap URL (default: {DEFAULT_SITEMAP})")
    ap.add_argument("--sitemap-file", help="Use a local sitemap XML file instead of fetching the sitemap.")
    ap.add_argument("--config", default="hdg_index_config.json", help="Optional JSON config file.")
    ap.add_argument("--output", default="hdg_index_check", help="Output directory.")
    ap.add_argument("--metadata-only", action="store_true", help="Skip sitemap comparison and validate metadata only.")
    args = ap.parse_args()

    index_path = Path(args.index)
    if not index_path.exists():
        print(f"ERROR: index not found: {index_path}", file=sys.stderr)
        return 2

    config = load_config(Path(args.config) if args.config else None)
    articles = parse_index(index_path)
    issues = validate_metadata(articles)

    sitemap_urls = None
    new_urls: list[str] = []
    stale_urls: list[str] = []

    if not args.metadata_only:
        try:
            if args.sitemap_file:
                sitemap_urls = collect_sitemap_urls_from_file(Path(args.sitemap_file))
            else:
                sitemap_urls = collect_sitemap_urls(args.sitemap)
        except Exception as e:
            print(f"WARNING: sitemap check failed: {e}", file=sys.stderr)
            print("Metadata validation will still complete.", file=sys.stderr)
            sitemap_urls = None

    if sitemap_urls is not None:
        indexed = {norm_url(a.url) for a in articles if a.url}
        sitemap_article_like = {u for u in sitemap_urls if not is_probable_non_article(u, config)}
        new_urls = sorted(sitemap_article_like - indexed)
        stale_urls = sorted(indexed - sitemap_urls)

    out_dir = Path(args.output)
    write_report(
        out_dir=out_dir,
        articles=articles,
        issues=issues,
        new_urls=new_urls,
        stale_urls=stale_urls,
        sitemap_count=len(sitemap_urls) if sitemap_urls is not None else None,
    )
    write_new_article_stubs(out_dir, new_urls, articles)

    errors = sum(1 for x in issues if x["level"] == "ERROR")
    reviews = sum(1 for x in issues if x["level"] == "REVIEW")

    print("HDG index check complete")
    print(f"  indexed articles: {len(articles)}")
    print(f"  metadata errors: {errors}")
    print(f"  review flags: {reviews}")
    if sitemap_urls is not None:
        print(f"  sitemap URLs: {len(sitemap_urls)}")
        print(f"  new/unindexed URLs: {len(new_urls)}")
        print(f"  indexed URLs absent from sitemap: {len(stale_urls)}")
    print(f"  report: {out_dir / 'HDG_Index_Validation_Report.md'}")
    print(f"  new stubs: {out_dir / 'HDG_New_Article_Stubs.txt'}")

    # Errors fail CI; REVIEW flags do not.
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
