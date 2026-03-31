#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path


YEAR_RE = re.compile(r"\b(?:17|18|19|20)\d{2}[a-z]?\b")
QUOTE_TITLE_RE = re.compile(r'[“"]([^"”]{6,240})[”"]')
SINGLE_QUOTE_TITLE_RE = re.compile(r"(?:^|[\s(])['‘]([^'’]{6,240})[’'](?=$|[\s,.;:?!)])")
START_PATTERNS = [
    re.compile(r'(?<=[.?!”"])\s+(?=[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ\'`’.\-]+,\s+[A-ZÀ-ÖØ-Ý])'),
    re.compile(r'(?<=[.?!”"])\s+(?=[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ\'`’.\-]+\s*\(\d{4}[a-z]?\))'),
    re.compile(r'(?<=[.?!”"])\s+(?=[A-Z]{2,},\s*\d{4}[a-z]?\b)'),
]
JUNK_PREFIX_RE = re.compile(
    r"^(?:\d{4}\]|\d+\]?|advance access publication date:.*?|published by .*?|for permissions,.*?|all rights reserved\.?)\s*",
    re.IGNORECASE,
)
TRAILING_SOURCE_PATTERNS = [
    re.compile(r",\s+(?:Journal|Review|Quarterly Journal|American Journal|American Economic Review|World Development|Landscape and Urban Planning|Sociology of Education|Regional Science and Urban Economics|Economic History Review)\b", re.IGNORECASE),
    re.compile(r"\.\s+(?:J\.|Q\.|Am\.|Rev\.|Journal|Review|Quarterly|American|World|Regional|Landscape|Sociology|Economic|Explorations|Cambridge|Princeton|Stanford|Oxford|Palgrave|Springer|Elsevier|Harcourt|Wallstein|Fischer)\b"),
    re.compile(r",\s+vol\.", re.IGNORECASE),
    re.compile(r",\s+pp\.", re.IGNORECASE),
    re.compile(r"\.\s+vol\.", re.IGNORECASE),
    re.compile(r"\.\s+pp\.", re.IGNORECASE),
    re.compile(r",\s+(?:Working Paper|Official Document|Master'?s thesis|Diss:|Dissertation)\b", re.IGNORECASE),
    re.compile(r"\.\s+(?:Working Paper|Official Document|Master'?s thesis|Diss:|Dissertation)\b", re.IGNORECASE),
    re.compile(r",\s+(?:Cambridge|Princeton|Stanford|Oxford|New York|London|Berkeley|Delhi):\s", re.IGNORECASE),
    re.compile(r"\bPolicy Research Working Papers\b.*", re.IGNORECASE),
    re.compile(r"\bHarvard Dataverse\b.*", re.IGNORECASE),
    re.compile(r"\bNational Bureau of Economic Research\b.*", re.IGNORECASE),
    re.compile(r"\b(?:Cambridge|Princeton|Stanford|Oxford) University Press\b.*", re.IGNORECASE),
    re.compile(r"\b(?:CRC Press|Palgrave Macmillan|Springer|Elsevier|Harcourt Brace|Wallstein Verlag|Fischer Verlag)\b.*", re.IGNORECASE),
    re.compile(r"\bTransport Infrastruc.*", re.IGNORECASE),
    re.compile(r"\bStatistik des Deutschen Reiches\b.*", re.IGNORECASE),
]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00ad", "")).strip()


def strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def clean_reference_text(text: str) -> str:
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\bdoi:\s*\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"©\s*The Author\(s\).*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"Published by .*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"Advance Access Publication Date:.*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[fileUNF]\b", " ", text)
    return normalize_space(text)


def split_combined_references(text: str) -> list[str]:
    rewritten = text
    for pattern in START_PATTERNS:
        rewritten = pattern.sub("\n", rewritten)
    chunks = [normalize_space(chunk) for chunk in rewritten.splitlines()]
    return [chunk for chunk in chunks if chunk]


def title_key(title: str) -> str:
    normalized = strip_accents(title).lower()
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    return normalize_space(normalized)


def clean_title(title: str) -> str:
    title = normalize_space(title)
    title = title.strip(" '\"‘’“”.,;:-")
    title = re.sub(r"\s+([,.;:?!])", r"\1", title)
    title = re.sub(r"\b([A-Z])\s+([A-Z])\b", r"\1\2", title)
    for pattern in TRAILING_SOURCE_PATTERNS:
        match = pattern.search(title)
        if match:
            title = title[: match.start()]
    sentence_break = re.search(r"\.\s+[A-ZÀ-ÖØ-Ý][a-zà-ÿ]{2,}", title)
    if sentence_break:
        title = title[: sentence_break.start() + 1]
    title = re.sub(r"\.\s+[A-Z]$", "", title)
    title = re.sub(r",\s+[A-Z][a-z]{0,2}$", "", title)
    title = normalize_space(title)
    title = title.strip(" '\"‘’“”.,;:-")
    title = re.sub(r"\s{2,}", " ", title)
    return title


def plausible_title(title: str) -> bool:
    lowered = title.lower()
    if len(title) < 6 or len(title) > 240:
        return False
    if len(title.split()) < 2:
        return False
    if re.match(r"^\d", title):
        return False
    if re.match(r"^[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ'`’.\-]+,\s+[A-ZÀ-ÖØ-Ý]", title):
        return False
    if re.match(r"^[ivxlcdm]+\b", lowered):
        return False
    if lowered.startswith(("journal of", "review of", "american economic review", "quarterly journal")):
        return False
    if lowered.startswith(("available at", "published by", "for permissions", "all rights reserved")):
        return False
    if "https://" in lowered or "http://" in lowered or "doi.org" in lowered:
        return False
    if " vol." in lowered or " pp." in lowered:
        return False
    if " published online" in lowered:
        return False
    if "author(s)" in lowered:
        return False
    if lowered in {"references", "bibliography"}:
        return False
    if lowered.endswith(("journal", "review", "press", "university press")):
        return False
    if lowered.endswith((" j", " rev", " econ", " res")):
        return False
    if title.count('"') or title.count("'") > 2:
        return False
    letters = sum(ch.isalpha() for ch in title)
    return letters >= 5


def extract_quoted_titles(text: str) -> list[str]:
    titles: list[str] = []
    for match in QUOTE_TITLE_RE.finditer(text):
        title = clean_title(match.group(1))
        if plausible_title(title):
            titles.append(title)
    for match in SINGLE_QUOTE_TITLE_RE.finditer(text):
        title = clean_title(match.group(1))
        if plausible_title(title):
            titles.append(title)
    return titles


def extract_unquoted_title(text: str) -> str | None:
    working = JUNK_PREFIX_RE.sub("", text)
    year_match = YEAR_RE.search(working)
    if not year_match:
        return None

    tail = working[year_match.end() :]
    tail = re.sub(r"^[\s\]\).,:;'-]+", "", tail)
    if not tail:
        return None

    markers = [
        r"\.\s+(?:[A-Z][a-z]+\.)",
        r"\.\s+In\b",
        r"\.\s+[A-Z][a-z]+:",
        r"\.\s+[A-Z][A-Za-z&\- ]{3,}$",
    ]
    best_end: int | None = None
    for marker in markers:
        match = re.search(marker, tail)
        if match:
            candidate_end = match.start() + 1
            if best_end is None or candidate_end < best_end:
                best_end = candidate_end

    if best_end is None:
        sentence = re.search(r"^(.{6,220}?[.?!])(?:\s|$)", tail)
        if sentence:
            best_end = sentence.end(1)
        else:
            best_end = min(len(tail), 220)

    title = clean_title(tail[:best_end])
    if plausible_title(title):
        return title
    return None


def extract_titles(text: str) -> list[str]:
    titles: list[str] = []
    for chunk in split_combined_references(clean_reference_text(text)):
        quoted = extract_quoted_titles(chunk)
        if quoted:
            titles.extend(quoted)
            continue
        unquoted = extract_unquoted_title(chunk)
        if unquoted:
            titles.append(unquoted)
    return titles


def write_outputs(input_csv: Path, output_dir: Path) -> tuple[Path, Path]:
    with input_csv.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    seen: set[str] = set()
    titles: list[str] = []
    for row in rows:
        for title in extract_titles(row["reference_text"]):
            key = title_key(title)
            if not key or key in seen:
                continue
            seen.add(key)
            titles.append(title)

    titles.sort(key=title_key)

    csv_path = output_dir / "development_reference_titles_only.csv"
    txt_path = output_dir / "development_reference_titles_only.txt"

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["title"])
        writer.writeheader()
        for title in titles:
            writer.writerow({"title": title})

    with txt_path.open("w", encoding="utf-8") as handle:
        for title in titles:
            handle.write(f"{title}\n")

    return csv_path, txt_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract title-only reference list from cleaned references.")
    parser.add_argument("input_csv", type=Path, help="CSV with a reference_text column.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_csv = args.input_csv.expanduser().resolve()
    output_dir = (args.output_dir.expanduser().resolve() if args.output_dir else input_csv.parent)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path, txt_path = write_outputs(input_csv=input_csv, output_dir=output_dir)
    sys.stdout.write(f"{csv_path}\n{txt_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
