#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests
import yaml
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
NOTES_ROOT = ROOT / "Notes"
if not NOTES_ROOT.exists():
    NOTES_ROOT = ROOT / "Reading Notes"
REFERENCE_ROOT = ROOT / "Reference"
if not REFERENCE_ROOT.exists():
    REFERENCE_ROOT = ROOT / "reference"
REPORT_ROOT = ROOT / "_Preprocess"
DUPLICATE_ROOT = ROOT / "_Duplicates"
TODAY = date.today().isoformat()
USER_AGENT = "Codex Literature Vault Sync/2.0 (mailto:no-reply@example.com)"
NOTES_FOLDER_NAME = NOTES_ROOT.name

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)

SYSTEM_DIR_NAMES = {
    ".git",
    ".obsidian",
    ".claude",
    "_Preprocess",
    "_Duplicates",
    "Notes",
    "Reading Notes",
    "Reference",
    "reference",
    "Diary",
}

SURNAME_PREFIXES = {
    "al",
    "bin",
    "da",
    "de",
    "del",
    "della",
    "der",
    "di",
    "du",
    "la",
    "le",
    "san",
    "st",
    "van",
    "von",
}

STOPWORDS = {
    "about",
    "after",
    "among",
    "before",
    "between",
    "beyond",
    "bureaucracy",
    "capacity",
    "china",
    "courts",
    "development",
    "digital",
    "effects",
    "evidence",
    "from",
    "government",
    "judicial",
    "law",
    "lawyers",
    "legal",
    "political",
    "politics",
    "public",
    "rule",
    "state",
    "study",
    "surveillance",
    "system",
    "through",
    "using",
    "with",
}

COUNTRY_PATTERNS = {
    "Afghanistan": re.compile(r"\bafghanistan\b", re.IGNORECASE),
    "Bangladesh": re.compile(r"\bbangladesh\b", re.IGNORECASE),
    "Brazil": re.compile(r"\bbrazil\b", re.IGNORECASE),
    "China": re.compile(r"\bchina\b|\bchinese\b", re.IGNORECASE),
    "France": re.compile(r"\bfrance\b|\bfrench\b", re.IGNORECASE),
    "India": re.compile(r"\bindia\b|\bindian\b", re.IGNORECASE),
    "Indonesia": re.compile(r"\bindonesia\b|\bindonesian\b", re.IGNORECASE),
    "Kenya": re.compile(r"\bkenya\b|\bkenyan\b", re.IGNORECASE),
    "Latin America": re.compile(r"\blatin america\b", re.IGNORECASE),
    "Mexico": re.compile(r"\bmexico\b|\bmexican\b", re.IGNORECASE),
    "Nigeria": re.compile(r"\bnigeria\b|\bnigerian\b", re.IGNORECASE),
    "Pakistan": re.compile(r"\bpakistan\b|\bpakistani\b", re.IGNORECASE),
    "Poland": re.compile(r"\bpoland\b|\bpolish\b", re.IGNORECASE),
    "Russia": re.compile(r"\brussia\b|\brussian\b", re.IGNORECASE),
    "South Africa": re.compile(r"\bsouth africa\b", re.IGNORECASE),
    "United Kingdom": re.compile(r"\bunited kingdom\b|\bbritain\b|\bbritish\b", re.IGNORECASE),
    "United States": re.compile(r"\bunited states\b|\bu\.s\.\b|\bamerica\b|\bamerican\b", re.IGNORECASE),
}

METHOD_PATTERNS = {
    "field experiment": [r"\bfield experiment\b", r"\brandomized field\b"],
    "survey experiment": [r"\bsurvey experiment\b"],
    "natural experiment": [r"\bnatural experiment\b"],
    "difference-in-differences": [r"\bdifference[- ]in[- ]differences\b", r"\bdid\b"],
    "regression discontinuity": [r"\bregression discontinuity\b", r"\brdd\b"],
    "instrumental variables": [r"\binstrumental variables?\b", r"\biv\b"],
    "panel data": [r"\bpanel data\b"],
    "administrative data": [r"\badministrative data\b"],
    "observational data": [r"\bobservational data\b"],
    "computational text analysis": [r"\btext analysis\b", r"\bnlp\b", r"\bcomputational\b"],
    "case study": [r"\bcase study\b", r"\bcomparative case\b"],
    "archival research": [r"\barchival\b"],
    "formal theory": [r"\bformal model\b", r"\bformal theory\b"],
}

KNOWN_JOURNALS = {
    "aer": "American Economic Review",
    "aej_app": "American Economic Journal: Applied Economics",
    "aejapplied": "American Economic Journal: Applied Economics",
    "aejmacro": "American Economic Journal: Macroeconomics",
    "aejmicro": "American Economic Journal: Microeconomics",
    "aej_micro": "American Economic Journal: Microeconomics",
    "aejpolicy": "American Economic Journal: Economic Policy",
    "ajls": "Asian Journal of Law and Society",
    "ajps": "American Journal of Political Science",
    "apsr": "American Political Science Review",
    "arlss": "Annual Review of Law and Social Science",
    "arps": "Annual Review of Political Science",
    "bjps": "British Journal of Political Science",
    "cq": "The China Quarterly",
    "cps": "Comparative Political Studies",
    "ecma": "Econometrica",
    "ej": "The Economic Journal",
    "io": "International Organization",
    "jde": "Journal of Development Economics",
    "jeea": "Journal of the European Economic Association",
    "jlc": "Journal of Law and Courts",
    "jop": "The Journal of Politics",
    "jpe": "Journal of Political Economy",
    "jpube": "Journal of Public Economics",
    "jpubeco": "Journal of Public Economics",
    "lsi": "Law & Social Inquiry",
    "lsr": "Law & Society Review",
    "polcomm": "Political Communication",
    "psrm": "Political Science Research and Methods",
    "qje": "Quarterly Journal of Economics",
    "restat": "The Review of Economics and Statistics",
    "restud": "Review of Economic Studies",
    "wp": "World Politics",
}

FALLBACK_TITLE_SKIP = {
    "abstract",
    "authors",
    "citation",
    "copyright information",
    "doi",
    "email",
    "keywords",
    "permalink",
    "publication date",
    "title",
}

BOILERPLATE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^american political science review$",
        r"^the journal of politics$",
        r"^american economic review$",
        r"^publication date$",
        r"^permalink$",
        r"^doi$",
        r"^title$",
        r"^keywords$",
        r"^author[s]?$",
        r"^original article$",
        r"^research article$",
        r"^this pdf is a selection from",
        r"^terms of use:",
        r"^copyright",
        r"^published by",
        r"^working paper",
        r"^department of",
    ]
]


@dataclass(frozen=True)
class CollectionSpec:
    pdf_dir: str
    note_dir: str
    category: str
    bib_name: str
    source: str = "explicit"

    @property
    def pdf_path(self) -> Path:
        return ROOT / self.pdf_dir

    @property
    def note_path(self) -> Path:
        return NOTES_ROOT / self.note_dir

    @property
    def bib_path(self) -> Path:
        return REFERENCE_ROOT / self.bib_name


EXPLICIT_COLLECTIONS = {
    "Authoritarianism": CollectionSpec(
        "Authoritarianism",
        "Authoritarian Politics",
        "Authoritarian Politics",
        "authoritarian_politics.bib",
    ),
    "Bureaucracy": CollectionSpec(
        "Bureaucracy",
        "Developing Country Bureaucracy and Accountability",
        "Developing Country Bureaucracy and Accountability",
        "developing_country_bureaucracy_accountability.bib",
    ),
    "Dissertation": CollectionSpec(
        "Dissertation",
        "Good Dissertation",
        "Good Dissertation",
        "good_dissertation.bib",
    ),
    "Information": CollectionSpec(
        "Information",
        "China Censorship Propaganda and Public Opinion",
        "China Censorship Propaganda and Public Opinion",
        "china_censorship_propaganda_and_public_opinion.bib",
    ),
    "Law": CollectionSpec(
        "Law",
        "Lawyers and Courts",
        "Lawyers and Courts",
        "lawyers_and_courts.bib",
    ),
    "Method": CollectionSpec("Method", "Method", "Method", "method.bib"),
    "RCT": CollectionSpec("RCT", "RCT", "RCT", "rct.bib"),
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "collection"


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", " ", text).strip().lower()


def unique_preserve_order(items: list[Any]) -> list[Any]:
    output: list[Any] = []
    seen: set[Any] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    data = yaml.safe_load(match.group(1)) or {}
    return data, text[match.end() :]


def dump_frontmatter(data: dict[str, Any]) -> str:
    raw = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False).strip()
    return f"---\n{raw}\n---\n"


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if value == "":
        return []
    return [value]


def coerce_year(value: Any) -> Any:
    if isinstance(value, int):
        return value
    text = normalize_space(str(value or ""))
    return int(text) if text.isdigit() else text


def discover_collections(filters: set[str] | None = None) -> list[CollectionSpec]:
    specs: list[CollectionSpec] = []
    seen: set[str] = set()
    for child in sorted(ROOT.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir():
            continue
        if child.name in SYSTEM_DIR_NAMES or child.name.startswith("."):
            continue
        if filters and child.name not in filters and child.name.replace("_", " ") not in filters:
            if child.name not in EXPLICIT_COLLECTIONS:
                continue
            spec = EXPLICIT_COLLECTIONS[child.name]
            if spec.note_dir not in filters and spec.category not in filters:
                continue
        pdf_count = sum(1 for _ in child.glob("*.pdf"))
        if pdf_count == 0:
            continue
        if child.name in EXPLICIT_COLLECTIONS:
            spec = EXPLICIT_COLLECTIONS[child.name]
        else:
            note_dir = child.name
            bib_name = f"{slugify(child.name)}.bib"
            spec = CollectionSpec(child.name, note_dir, note_dir, bib_name, source="auto")
        if spec.pdf_dir in seen:
            continue
        seen.add(spec.pdf_dir)
        specs.append(spec)
    return specs


def build_pdf_folder_map(collections: list[CollectionSpec]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for spec in collections:
        mapping[spec.pdf_dir] = spec.pdf_dir
        mapping[spec.note_dir] = spec.pdf_dir
        mapping[spec.category] = spec.pdf_dir
    return mapping


def list_source_notes(note_dir: Path) -> dict[str, Path]:
    notes: dict[str, Path] = {}
    if not note_dir.exists():
        return notes
    for note_path in sorted(note_dir.glob("*.md")):
        if note_path.name.startswith("_"):
            continue
        if note_path.stat().st_size == 0:
            continue
        notes[note_path.stem] = note_path
    return notes


def load_note(note_path: Path) -> tuple[dict[str, Any], str]:
    return parse_frontmatter(note_path.read_text(errors="ignore"))


def note_quality(frontmatter: dict[str, Any], body: str) -> int:
    tags = set(str(tag) for tag in ensure_list(frontmatter.get("tags")))
    score = len(body.split())
    status = normalize_space(str(frontmatter.get("status") or "")).lower()
    if status == "synthesized":
        score += 300
    elif status == "organized":
        score += 180
    elif status == "imported-metadata":
        score -= 180
    if "metadata-review" in tags:
        score -= 160
    if "needs-summary" in tags:
        score -= 120
    if "## One-Sentence Takeaway" in body:
        score += 140
    if "## Core Argument" in body:
        score += 120
    if "## Research Question" in body:
        score += 80
    return score


def note_is_stub(note_path: Path | None) -> bool:
    if note_path is None or not note_path.exists():
        return True
    frontmatter, body = load_note(note_path)
    status = normalize_space(str(frontmatter.get("status") or "")).lower()
    tags = set(str(tag) for tag in ensure_list(frontmatter.get("tags")))
    if status == "imported-metadata":
        return True
    if "metadata-review" in tags:
        return True
    if "needs-summary" in tags and len(body.split()) < 280:
        return True
    if len(body.split()) < 180 and "## Basic Information" in body and "## Abstract / Extracted Summary" in body:
        return True
    return False


def parse_stem(stem: str) -> dict[str, str]:
    tokens = stem.split("_")
    copy_suffix = ""
    if tokens and (re.fullmatch(r"\d{1,2}", tokens[-1]) or re.fullmatch(r"[a-z]", tokens[-1])):
        copy_suffix = tokens.pop()
    year_index = -1
    year = ""
    for idx, token in enumerate(tokens):
        if re.fullmatch(r"(19|20)\d{2}", token):
            year_index = idx
            year = token
            break
    author = "_".join(tokens[:year_index]) if year_index > 0 else (tokens[0] if tokens else "")
    abbr = "_".join(tokens[year_index + 1 :]) if year_index >= 0 else ""
    return {
        "author": author,
        "year": year,
        "abbr": abbr,
        "copy_suffix": copy_suffix,
    }


def looks_standardized_stem(stem: str) -> bool:
    if not re.fullmatch(r"[a-z0-9_]+", stem):
        return False
    parsed = parse_stem(stem)
    return bool(parsed["author"] and parsed["year"] and parsed["abbr"])


def strip_copy_suffix(stem: str) -> str:
    parsed = parse_stem(stem)
    if not parsed["copy_suffix"]:
        return stem
    return stem[: -(len(parsed["copy_suffix"]) + 1)]


def extract_pdf_text(pdf_path: Path, pages: int = 2) -> str:
    try:
        proc = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(pages), str(pdf_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout
    except Exception:
        return ""


def extract_doi(*chunks: str) -> str:
    for chunk in chunks:
        if not chunk:
            continue
        match = DOI_RE.search(chunk)
        if match:
            return match.group(0).rstrip(").,;").lower()
    return ""


def title_from_pdf_metadata(pdf_path: Path) -> tuple[str, str]:
    try:
        reader = PdfReader(str(pdf_path))
        metadata = reader.metadata or {}
        title = normalize_space(str(metadata.get("/Title") or ""))
        author = normalize_space(str(metadata.get("/Author") or ""))
        return title, author
    except Exception:
        return "", ""


def is_plausible_title(title: str) -> bool:
    title = normalize_space(title)
    if len(title) < 12:
        return False
    if title.lower() in FALLBACK_TITLE_SKIP:
        return False
    letters = sum(ch.isalpha() for ch in title)
    digits = sum(ch.isdigit() for ch in title)
    if letters < 8 or digits > letters:
        return False
    return True


def title_from_text(text: str) -> str:
    lines = [normalize_space(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    for idx, line in enumerate(lines[:60]):
        if line.lower().startswith("title"):
            tail = normalize_space(line[5:].strip(" :.-"))
            if is_plausible_title(tail):
                return tail.rstrip(".")
            collected: list[str] = []
            for candidate in lines[idx + 1 : idx + 6]:
                lower = candidate.lower()
                if lower in FALLBACK_TITLE_SKIP or candidate.startswith("http") or len(candidate) > 180:
                    break
                if DOI_RE.search(candidate):
                    break
                collected.append(candidate)
            joined = normalize_space(" ".join(collected)).rstrip(".")
            if is_plausible_title(joined):
                return joined
    candidates: list[str] = []
    for line in lines[:40]:
        lower = line.lower()
        if lower in FALLBACK_TITLE_SKIP:
            continue
        if any(pattern.search(line) for pattern in BOILERPLATE_PATTERNS):
            continue
        if line.startswith("http") or DOI_RE.search(line):
            continue
        if len(line) < 12 or len(line) > 180:
            continue
        candidates.append(line)
    for line in candidates:
        if is_plausible_title(line):
            return line.rstrip(".")
    return ""


def extract_abstract_from_text(text: str) -> str:
    lines = [normalize_space(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    for idx, line in enumerate(lines[:120]):
        lower = line.lower()
        if lower == "abstract" or lower.startswith("abstract "):
            collected: list[str] = []
            tail = normalize_space(re.sub(r"^abstract[:\s-]*", "", line, flags=re.IGNORECASE))
            if tail:
                collected.append(tail)
            for candidate in lines[idx + 1 : idx + 30]:
                cand_lower = candidate.lower()
                if cand_lower.startswith("keywords") or cand_lower == "introduction":
                    break
                if re.match(r"^\d+\.?\s+introduction", cand_lower):
                    break
                if len(" ".join(collected + [candidate])) > 2200:
                    break
                collected.append(candidate)
                if len(" ".join(collected)) > 500 and candidate.endswith("."):
                    break
            abstract = normalize_space(" ".join(collected))
            if 50 <= len(abstract) <= 2200:
                return abstract
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    for paragraph in paragraphs[:8]:
        cleaned = normalize_space(paragraph)
        if 350 <= len(cleaned) <= 1800 and not DOI_RE.search(cleaned):
            return cleaned
    return ""


def author_list_from_crossref(message: dict[str, Any]) -> list[str]:
    authors: list[str] = []
    for item in message.get("author") or []:
        given = normalize_space(item.get("given") or "")
        family = normalize_space(item.get("family") or "")
        full = normalize_space(f"{given} {family}")
        if full:
            authors.append(full)
    return authors


def year_from_crossref(message: dict[str, Any]) -> str:
    for key in ["published-print", "published-online", "published", "issued", "created"]:
        parts = (((message.get(key) or {}).get("date-parts") or [[None]])[0] or [None])
        if parts and parts[0]:
            return str(parts[0])
    return ""


def parse_crossref_abstract(raw: str | None) -> str:
    if not raw:
        return ""
    cleaned = html.unescape(raw)
    cleaned = re.sub(r"</?(jats:)?(?:p|italic|title|sec|bold|sc|sup|sub|xref|ext-link|inline-formula)[^>]*>", " ", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return normalize_space(cleaned)


def normalize_pages(message: dict[str, Any]) -> str:
    return normalize_space(str(message.get("page") or ""))


def entry_type_from_crossref(message: dict[str, Any], collection_name: str) -> str:
    type_name = normalize_space(str(message.get("type") or "")).lower()
    if type_name == "journal-article":
        return "article"
    if type_name == "book":
        return "book"
    if type_name == "book-chapter":
        return "incollection"
    if type_name == "report":
        return "techreport"
    if type_name == "dissertation" or collection_name == "Good Dissertation":
        return "phdthesis"
    return "misc"


def infer_journal_abbr(venue: str, fallback: str = "") -> str:
    fallback = normalize_space(fallback).lower()
    if fallback:
        return fallback
    normalized = normalize_title(venue)
    if not normalized:
        return ""
    preferred = [
        ("american economic journal applied economics", "aejapplied"),
        ("american economic journal economic policy", "aejpolicy"),
        ("american economic journal macroeconomics", "aejmacro"),
        ("american economic journal microeconomics", "aejmicro"),
        ("journal of public economics", "jpubeco"),
        ("review of economic studies", "restud"),
        ("review of economics and statistics", "restat"),
        ("american political science review", "apsr"),
        ("american journal of political science", "ajps"),
        ("journal of political economy", "jpe"),
        ("journal of development economics", "jde"),
        ("journal of the european economic association", "jeea"),
        ("the economic journal", "ej"),
        ("econometrica", "ecma"),
        ("quarterly journal of economics", "qje"),
        ("british journal of political science", "bjps"),
        ("comparative political studies", "cps"),
        ("world politics", "wp"),
        ("international organization", "io"),
        ("political science research and methods", "psrm"),
        ("political communication", "polcomm"),
        ("journal of law and courts", "jlc"),
    ]
    for venue_key, abbr in preferred:
        if venue_key in normalized:
            return abbr
    for abbr, display in KNOWN_JOURNALS.items():
        display_norm = normalize_title(display)
        if display_norm == normalized or display_norm in normalized or normalized in display_norm:
            return abbr
    return ""


def first_author_slug(name: str) -> str:
    name = normalize_space(name)
    if not name:
        return ""
    if "," in name:
        family = normalize_space(name.split(",", 1)[0])
        return slugify(family)
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    tokens = [token for token in re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)?", ascii_name) if token]
    if not tokens:
        return ""
    if len(tokens) == 1:
        return slugify(tokens[0])
    family_tokens = [tokens[-1]]
    if len(tokens) >= 2 and tokens[-2].lower() in SURNAME_PREFIXES:
        family_tokens = [tokens[-2], tokens[-1]]
    family = " ".join(family_tokens)
    return slugify(family)


def infer_regions(*chunks: str) -> list[str]:
    combined = "\n".join(chunk for chunk in chunks if chunk)
    regions = [label for label, pattern in COUNTRY_PATTERNS.items() if pattern.search(combined)]
    return unique_preserve_order(regions)


def infer_methods(*chunks: str) -> list[str]:
    combined = " ".join(chunks).lower()
    methods: list[str] = []
    for label, patterns in METHOD_PATTERNS.items():
        if any(re.search(pattern, combined) for pattern in patterns):
            methods.append(label)
    return methods


def significant_title_tokens(title: str) -> set[str]:
    tokens = normalize_title(title).split()
    return {token for token in tokens if len(token) >= 4 and token not in STOPWORDS}


def note_entry_type(metadata: dict[str, Any], collection_name: str) -> str:
    if collection_name == "Good Dissertation":
        return "phdthesis"
    abbr = normalize_space(str(metadata.get("journal_abbr") or "")).lower()
    venue = normalize_space(str(metadata.get("venue") or ""))
    if abbr:
        return "article"
    if venue and any(token in venue.lower() for token in ["university", "school", "harvard", "stanford", "mit", "princeton"]):
        return "phdthesis"
    return "misc"


def bibtex_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def build_bib_entry(key: str, metadata: dict[str, Any], pdf_path: Path, collection_name: str) -> str:
    entry_type = metadata.get("entry_type") or note_entry_type(metadata, collection_name)
    fields: list[tuple[str, str]] = []
    authors = metadata.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    author_value = " and ".join(normalize_space(str(author)) for author in authors if normalize_space(str(author)))
    title = normalize_space(str(metadata.get("title") or pdf_path.stem.replace("_", " ")))
    year = normalize_space(str(metadata.get("year") or ""))
    venue = normalize_space(str(metadata.get("venue") or ""))
    if author_value:
        fields.append(("author", author_value))
    fields.append(("title", title))
    if entry_type == "article" and venue:
        fields.append(("journal", venue))
    elif entry_type == "phdthesis" and venue:
        fields.append(("school", venue))
    elif entry_type == "incollection" and venue:
        fields.append(("booktitle", venue))
    elif venue:
        fields.append(("howpublished", venue))
    if year:
        fields.append(("year", year))
    for field_name in ["volume", "issue", "pages", "publisher", "doi", "url"]:
        value = normalize_space(str(metadata.get(field_name) or ""))
        if not value:
            continue
        mapped = "number" if field_name == "issue" else field_name
        fields.append((mapped, value))
    note = normalize_space(str(metadata.get("note") or ""))
    if note:
        fields.append(("note", note))
    fields.append(("file", str(pdf_path)))
    lines = [f"@{entry_type}{{{key},"]
    for field_name, value in fields:
        lines.append(f"  {field_name} = {{{bibtex_escape(value)}}},")
    lines.append("}")
    return "\n".join(lines)


def score_crossref_candidate(
    message: dict[str, Any],
    title: str,
    year: str,
    author_token: str,
    venue: str,
) -> float:
    candidate_title = normalize_space(((message.get("title") or [""])[0]))
    score = SequenceMatcher(None, normalize_title(title), normalize_title(candidate_title)).ratio()
    candidate_year = year_from_crossref(message)
    if year and candidate_year == year:
        score += 0.08
    candidate_authors = " ".join(author_list_from_crossref(message)).lower()
    if author_token and author_token.lower() in candidate_authors:
        score += 0.06
    container = " ".join(message.get("container-title") or []).lower()
    if venue and normalize_title(venue) and normalize_title(venue) in normalize_title(container):
        score += 0.05
    return score


class MetadataResolver:
    def __init__(self, abbr_map: dict[str, str]) -> None:
        self.abbr_map = abbr_map
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.crossref_cache: dict[str, dict[str, Any] | None] = {}
        self.search_cache: dict[tuple[str, str, str, str], dict[str, Any] | None] = {}
        self.openalex_cache: dict[str, dict[str, Any] | None] = {}

    def crossref_by_doi(self, doi: str) -> dict[str, Any] | None:
        doi = doi.lower().strip()
        if not doi:
            return None
        if doi in self.crossref_cache:
            return self.crossref_cache[doi]
        try:
            response = self.session.get(
                f"https://api.crossref.org/works/{requests.utils.quote(doi, safe='')}",
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            message = payload.get("message") or {}
            self.crossref_cache[doi] = message
            time.sleep(0.08)
            return message
        except Exception:
            self.crossref_cache[doi] = None
            return None

    def crossref_search(self, title: str, year: str, author_token: str, venue: str) -> dict[str, Any] | None:
        cache_key = (title, year, author_token, venue)
        if cache_key in self.search_cache:
            return self.search_cache[cache_key]
        query = " ".join(part for part in [title, author_token, year, venue] if part)
        if not query:
            self.search_cache[cache_key] = None
            return None
        params = {
            "query.bibliographic": query,
            "rows": 8,
            "select": "DOI,title,author,container-title,type,URL,page,volume,issue,published-print,published-online,published,issued,publisher,abstract",
        }
        try:
            response = self.session.get("https://api.crossref.org/works", params=params, timeout=20)
            response.raise_for_status()
            items = ((response.json().get("message") or {}).get("items") or [])
            best_item = None
            best_score = 0.0
            for item in items:
                score = score_crossref_candidate(item, title, year, author_token, venue)
                if score > best_score:
                    best_item = item
                    best_score = score
            result = best_item if best_score >= 0.76 else None
            self.search_cache[cache_key] = result
            time.sleep(0.08)
            return result
        except Exception:
            self.search_cache[cache_key] = None
            return None

    def openalex_search(self, title: str, year: str) -> dict[str, Any] | None:
        cache_key = f"{title}|{year}"
        if cache_key in self.openalex_cache:
            return self.openalex_cache[cache_key]
        params = {"search": title, "per-page": 6, "mailto": "no-reply@example.com"}
        try:
            response = self.session.get("https://api.openalex.org/works", params=params, timeout=20)
            response.raise_for_status()
            results = response.json().get("results") or []
            best = None
            best_score = 0.0
            for item in results:
                candidate_title = normalize_space(item.get("display_name") or "")
                score = SequenceMatcher(None, normalize_title(title), normalize_title(candidate_title)).ratio()
                if year and str(item.get("publication_year") or "") == year:
                    score += 0.08
                if score > best_score:
                    best = item
                    best_score = score
            result = best if best_score >= 0.82 else None
            self.openalex_cache[cache_key] = result
            time.sleep(0.08)
            return result
        except Exception:
            self.openalex_cache[cache_key] = None
            return None

    def metadata_from_crossref(self, message: dict[str, Any], default_abbr: str, collection_name: str) -> dict[str, Any]:
        venue = normalize_space(((message.get("container-title") or [""])[0]))
        doi = normalize_space(str(message.get("DOI") or "")).lower()
        abbr = infer_journal_abbr(venue, default_abbr)
        return {
            "title": normalize_space(((message.get("title") or [""])[0])),
            "authors": author_list_from_crossref(message),
            "year": year_from_crossref(message),
            "venue": venue,
            "journal_abbr": abbr,
            "doi": doi,
            "url": normalize_space(str(message.get("URL") or (f"https://doi.org/{doi}" if doi else ""))),
            "abstract": parse_crossref_abstract(message.get("abstract")),
            "volume": normalize_space(str(message.get("volume") or "")),
            "issue": normalize_space(str(message.get("issue") or "")),
            "pages": normalize_pages(message),
            "publisher": normalize_space(str(message.get("publisher") or "")),
            "entry_type": entry_type_from_crossref(message, collection_name),
            "source": "crossref",
        }

    def metadata_from_openalex(self, item: dict[str, Any], default_abbr: str, collection_name: str) -> dict[str, Any]:
        doi = normalize_space(str(item.get("doi") or "")).replace("https://doi.org/", "").lower()
        venue = normalize_space((((item.get("primary_location") or {}).get("source") or {}).get("display_name") or ""))
        authors = [
            normalize_space(((author.get("author") or {}).get("display_name") or ""))
            for author in (item.get("authorships") or [])
            if normalize_space(((author.get("author") or {}).get("display_name") or ""))
        ]
        biblio = item.get("biblio") or {}
        first_page = normalize_space(str(biblio.get("first_page") or ""))
        last_page = normalize_space(str(biblio.get("last_page") or ""))
        pages = f"{first_page}-{last_page}".strip("-") if first_page or last_page else ""
        abbr = infer_journal_abbr(venue, default_abbr)
        return {
            "title": normalize_space(str(item.get("display_name") or "")),
            "authors": authors,
            "year": str(item.get("publication_year") or ""),
            "venue": venue,
            "journal_abbr": abbr,
            "doi": doi,
            "url": normalize_space(str((item.get("ids") or {}).get("doi") or (f"https://doi.org/{doi}" if doi else ""))),
            "abstract": "",
            "volume": normalize_space(str(biblio.get("volume") or "")),
            "issue": normalize_space(str(biblio.get("issue") or "")),
            "pages": pages,
            "publisher": "",
            "entry_type": "phdthesis" if collection_name == "Good Dissertation" else ("article" if venue else "misc"),
            "source": "openalex",
        }

    def normalize_note_metadata(self, data: dict[str, Any], collection_name: str) -> dict[str, Any]:
        authors = ensure_list(data.get("authors"))
        doi = normalize_space(str(data.get("doi") or "")).lower()
        venue = normalize_space(str(data.get("venue") or ""))
        abbr = infer_journal_abbr(venue, normalize_space(str(data.get("journal_abbr") or "")).lower())
        return {
            "title": normalize_space(str(data.get("title") or "")),
            "authors": [normalize_space(str(author)) for author in authors if normalize_space(str(author))],
            "year": str(data.get("year") or ""),
            "venue": venue,
            "journal_abbr": abbr,
            "doi": doi,
            "url": normalize_space(str(data.get("url") or (f"https://doi.org/{doi}" if doi else ""))),
            "abstract": "",
            "volume": "",
            "issue": "",
            "pages": "",
            "publisher": "",
            "entry_type": note_entry_type(data, collection_name),
            "source": "note",
        }

    def resolve_metadata(self, pdf_path: Path, spec: CollectionSpec, note_data: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = parse_stem(pdf_path.stem)
        text = extract_pdf_text(pdf_path)
        pdf_title, pdf_author = title_from_pdf_metadata(pdf_path)
        extracted_abstract = extract_abstract_from_text(text)
        note_meta = self.normalize_note_metadata(note_data or {}, spec.category) if note_data else {}

        doi_candidates = unique_preserve_order(
            [
                normalize_space(str(note_meta.get("doi") or "")).lower(),
                extract_doi(pdf_title, text),
            ]
        )
        for doi in doi_candidates:
            if not doi:
                continue
            message = self.crossref_by_doi(doi)
            if message:
                meta = self.metadata_from_crossref(message, note_meta.get("journal_abbr", "") or parsed["abbr"], spec.category)
                if not meta.get("abstract"):
                    meta["abstract"] = extracted_abstract
                return meta

        title_candidates = unique_preserve_order(
            [
                normalize_space(str(note_meta.get("title") or "")),
                pdf_title if is_plausible_title(pdf_title) else "",
                title_from_text(text),
            ]
        )
        author_token = ""
        if note_meta.get("authors"):
            author_token = first_author_slug(str((note_meta.get("authors") or [""])[0]))
        author_token = author_token or parsed["author"]
        venue = normalize_space(str(note_meta.get("venue") or self.abbr_map.get(parsed["abbr"], "")))

        for title in title_candidates:
            if not title:
                continue
            message = self.crossref_search(title, note_meta.get("year") or parsed["year"], author_token, venue)
            if message:
                meta = self.metadata_from_crossref(message, note_meta.get("journal_abbr", "") or parsed["abbr"], spec.category)
                if not meta.get("abstract"):
                    meta["abstract"] = extracted_abstract
                return meta
            item = self.openalex_search(title, note_meta.get("year") or parsed["year"])
            if item:
                meta = self.metadata_from_openalex(item, note_meta.get("journal_abbr", "") or parsed["abbr"], spec.category)
                if not meta.get("abstract"):
                    meta["abstract"] = extracted_abstract
                return meta

        title = next((title for title in title_candidates if title), "")
        authors = note_meta.get("authors") or ([pdf_author] if normalize_space(pdf_author) else [])
        year = normalize_space(str(note_meta.get("year") or parsed["year"]))
        venue = normalize_space(str(note_meta.get("venue") or self.abbr_map.get(parsed["abbr"], "")))
        abbr = infer_journal_abbr(venue, note_meta.get("journal_abbr", "") or parsed["abbr"])
        if not title:
            title = normalize_space(pdf_path.stem.replace("_", " "))
        return {
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venue,
            "journal_abbr": abbr,
            "doi": "",
            "url": "",
            "abstract": extracted_abstract,
            "volume": "",
            "issue": "",
            "pages": "",
            "publisher": "",
            "entry_type": "phdthesis" if spec.category == "Good Dissertation" else ("article" if abbr else "misc"),
            "note": "Metadata inferred from local PDF; review recommended.",
            "source": "fallback",
        }


def build_abbr_map(collections: list[CollectionSpec]) -> dict[str, str]:
    abbr_map = dict(KNOWN_JOURNALS)
    for spec in collections:
        note_dir = spec.note_path
        if not note_dir.exists():
            continue
        for note_path in note_dir.glob("*.md"):
            if note_path.name.startswith("_") or note_path.stat().st_size == 0:
                continue
            try:
                frontmatter, _ = load_note(note_path)
            except Exception:
                continue
            abbr = normalize_space(str(frontmatter.get("journal_abbr") or "")).lower()
            venue = normalize_space(str(frontmatter.get("venue") or ""))
            if abbr and venue:
                abbr_map.setdefault(abbr, venue)
    return abbr_map


def title_needs_replacement(title: str, stem: str) -> bool:
    normalized = normalize_space(title)
    if not normalized:
        return True
    if "metadata unresolved" in normalized.lower():
        return True
    if normalize_title(normalized) == normalize_title(stem.replace("_", " ")):
        return True
    return False


def build_desired_stem(current_stem: str, metadata: dict[str, Any]) -> str:
    if looks_standardized_stem(current_stem) and not parse_stem(current_stem)["copy_suffix"]:
        return current_stem
    parsed = parse_stem(current_stem)
    authors = metadata.get("authors") or []
    first_author = first_author_slug(str(authors[0])) if authors else ""
    author = first_author or parsed["author"] or slugify((metadata.get("title") or current_stem).split(" ")[0])
    year = normalize_space(str(metadata.get("year") or parsed["year"] or "undated"))
    abbr = infer_journal_abbr(str(metadata.get("venue") or ""), str(metadata.get("journal_abbr") or parsed["abbr"] or "misc"))
    abbr = slugify(abbr).replace("-", "_") if abbr else "misc"
    author = slugify(author).replace("-", "_")
    year = year if re.fullmatch(r"(19|20)\d{2}", year) else "undated"
    return f"{author}_{year}_{abbr}"


def hash_file(path: Path, cache: dict[Path, str]) -> str:
    if path in cache:
        return cache[path]
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    cache[path] = digest
    return digest


def files_identical(a: Path, b: Path, cache: dict[Path, str]) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    return hash_file(a, cache) == hash_file(b, cache)


def next_available_pdf_path(pdf_dir: Path, desired_stem: str, current_path: Path) -> Path:
    if current_path.stem == desired_stem:
        return current_path
    candidate = pdf_dir / f"{desired_stem}.pdf"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = pdf_dir / f"{desired_stem}_{index}.pdf"
        if not candidate.exists():
            return candidate
        index += 1


def duplicate_note_safe(current_note: Path | None, target_note: Path | None) -> bool:
    if current_note is None or not current_note.exists():
        return True
    if target_note is None or not target_note.exists():
        return True
    return note_is_stub(current_note) or note_is_stub(target_note)


def archive_duplicate_pdf(pdf_path: Path, spec: CollectionSpec) -> Path:
    archive_dir = DUPLICATE_ROOT / spec.pdf_dir
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / pdf_path.name
    if not target.exists():
        pdf_path.rename(target)
        return target
    index = 2
    while True:
        candidate = archive_dir / f"{pdf_path.stem}_{index}.pdf"
        candidate = candidate.with_suffix(".pdf")
        if not candidate.exists():
            pdf_path.rename(candidate)
            return candidate
        index += 1


def ensure_aliases(data: dict[str, Any], *aliases: str) -> None:
    alias_values = [normalize_space(str(alias)) for alias in ensure_list(data.get("aliases")) if normalize_space(str(alias))]
    for alias in aliases:
        alias = normalize_space(alias)
        if alias:
            alias_values.append(alias)
    data["aliases"] = unique_preserve_order(alias_values)


def merge_note_files(primary_path: Path, duplicate_path: Path, primary_stem: str, duplicate_stem: str) -> None:
    if not duplicate_path.exists():
        return
    if not primary_path.exists():
        duplicate_path.rename(primary_path)
        frontmatter, body = load_note(primary_path)
        ensure_aliases(frontmatter, duplicate_stem, primary_stem)
        primary_path.write_text(dump_frontmatter(frontmatter) + body.rstrip() + "\n")
        return

    primary_frontmatter, primary_body = load_note(primary_path)
    duplicate_frontmatter, duplicate_body = load_note(duplicate_path)
    primary_score = note_quality(primary_frontmatter, primary_body)
    duplicate_score = note_quality(duplicate_frontmatter, duplicate_body)
    if duplicate_score > primary_score:
        winner_frontmatter = duplicate_frontmatter
        winner_body = duplicate_body
    else:
        winner_frontmatter = primary_frontmatter
        winner_body = primary_body
    ensure_aliases(
        winner_frontmatter,
        primary_stem,
        duplicate_stem,
        *[str(alias) for alias in ensure_list(primary_frontmatter.get("aliases"))],
        *[str(alias) for alias in ensure_list(duplicate_frontmatter.get("aliases"))],
    )
    primary_path.write_text(dump_frontmatter(winner_frontmatter) + winner_body.rstrip() + "\n")
    duplicate_path.unlink()


def repair_pdf_links(text: str, folder_map: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        folder = match.group(1)
        filename = match.group(2)
        alias = match.group(3) or ""
        canonical = folder_map.get(folder, folder)
        return f"[[{canonical}/{filename}{alias}]]"

    return re.sub(r"\[\[([^/\]|]+)/([^|\]]+\.pdf)(\|[^\]]+)?\]\]", repl, text)


def repair_broken_self_pdf_links(body: str, spec: CollectionSpec, pdf_name: str) -> str:
    def repl(match: re.Match[str]) -> str:
        folder = match.group(1)
        filename = match.group(2)
        alias = match.group(3) or ""
        target = ROOT / folder / filename
        if target.exists():
            return match.group(0)
        return f"[[{spec.pdf_dir}/{pdf_name}{alias}]]"

    return re.sub(r"\[\[([^/\]|]+)/([^|\]]+\.pdf)(\|[^\]]+)?\]\]", repl, body)


def get_section(body: str, heading: str) -> str:
    pattern = re.compile(rf"(?ms)^## {re.escape(heading)}\n(.*?)(?=^## |\Z)")
    match = pattern.search(body)
    return match.group(1).strip() if match else ""


def upsert_section(body: str, heading: str, content: str) -> str:
    section = f"## {heading}\n{content.strip()}\n"
    pattern = re.compile(rf"(?ms)^## {re.escape(heading)}\n.*?(?=^## |\Z)")
    if pattern.search(body):
        updated = pattern.sub(section + "\n", body)
        return updated.rstrip() + "\n"
    if not body.strip():
        return section + "\n"
    return body.rstrip() + "\n\n" + section + "\n"


def normalize_note_heading(body: str, title: str) -> str:
    body = body.lstrip()
    lines = body.splitlines()
    if not lines:
        return f"# {title}\n"
    if lines[0].startswith("# "):
        lines[0] = f"# {title}"
    else:
        lines.insert(0, "")
        lines.insert(0, f"# {title}")
    while len(lines) > 1 and lines[1].strip() == f"# {title}":
        lines.pop(1)
    return "\n".join(lines).rstrip() + "\n"


def build_metadata_status_lines(metadata: dict[str, Any]) -> str:
    source = metadata.get("source") or "local"
    lines = [f"- Synced on {TODAY} from local PDF and metadata lookup."]
    if source == "fallback":
        lines.append("- Metadata is still partially inferred from the local file; manual review is recommended.")
    else:
        lines.append("- Core citation fields were refreshed from the PDF and external metadata.")
    return "\n".join(lines)


def build_basic_information_lines(metadata: dict[str, Any], spec: CollectionSpec, pdf_name: str) -> str:
    authors = ", ".join(str(author) for author in metadata.get("authors") or [])
    lines = [
        f"- Authors: {authors}",
        f"- Year: {metadata.get('year') or ''}",
        f"- Venue: {metadata.get('venue') or ''}",
        f"- DOI: {metadata.get('doi') or ''}",
        f"- PDF: [[{spec.pdf_dir}/{pdf_name}]]",
    ]
    if metadata.get("volume") or metadata.get("issue") or metadata.get("pages"):
        lines.append(
            "- Volume / Issue / Pages: "
            f"{metadata.get('volume') or ''} / {metadata.get('issue') or ''} / {metadata.get('pages') or ''}"
        )
    return "\n".join(lines)


def merge_frontmatter(
    frontmatter: dict[str, Any],
    metadata: dict[str, Any],
    spec: CollectionSpec,
    pdf_name: str,
    stem: str,
) -> dict[str, Any]:
    data = dict(frontmatter)
    title = normalize_space(str(data.get("title") or ""))
    resolved_title = normalize_space(str(metadata.get("title") or ""))
    if title_needs_replacement(title, stem) and resolved_title:
        title = resolved_title
    data["type"] = "source-note"
    data["title"] = title or resolved_title or stem.replace("_", " ")
    ensure_aliases(data, stem)
    authors = [normalize_space(str(author)) for author in ensure_list(data.get("authors")) if normalize_space(str(author))]
    if not authors:
        authors = [normalize_space(str(author)) for author in metadata.get("authors") or [] if normalize_space(str(author))]
    data["authors"] = authors
    data["year"] = coerce_year(data.get("year") or metadata.get("year") or "")
    venue = normalize_space(str(data.get("venue") or metadata.get("venue") or ""))
    data["venue"] = venue
    data["category"] = spec.category
    data["topics"] = ensure_list(data.get("topics"))
    data["keywords"] = ensure_list(data.get("keywords"))
    methods = [normalize_space(str(item)) for item in ensure_list(data.get("methods")) if normalize_space(str(item))]
    if not methods:
        methods = infer_methods(data["title"], str(metadata.get("abstract") or ""))
    data["methods"] = methods
    regions = [normalize_space(str(item)) for item in ensure_list(data.get("regions")) if normalize_space(str(item))]
    if not regions:
        regions = infer_regions(data["title"], str(metadata.get("abstract") or ""))
    data["regions"] = regions
    data["journal_abbr"] = infer_journal_abbr(venue, str(data.get("journal_abbr") or metadata.get("journal_abbr") or ""))
    data["cases"] = ensure_list(data.get("cases"))
    data["projects"] = ensure_list(data.get("projects"))
    data["status"] = data.get("status") or "imported-metadata"
    data["priority"] = data.get("priority") or "medium"
    data["rating"] = data.get("rating", None)
    data["pdf_local"] = f"[[{spec.pdf_dir}/{pdf_name}]]"
    doi = normalize_space(str(data.get("doi") or metadata.get("doi") or "")).lower()
    data["doi"] = doi
    data["url"] = normalize_space(str(data.get("url") or metadata.get("url") or (f"https://doi.org/{doi}" if doi else "")))
    data["zotero_key"] = normalize_space(str(data.get("zotero_key") or ""))
    data["date_added"] = data.get("date_added") or TODAY
    data["last_reviewed"] = TODAY
    tags = [normalize_space(str(tag)) for tag in ensure_list(data.get("tags")) if normalize_space(str(tag))]
    tags.extend(["literature", "source-note", slugify(spec.category).replace("_", "-")])
    if data["journal_abbr"]:
        tags.append(str(data["journal_abbr"]))
    if note_entry_type(data, spec.category) == "article":
        tags.append("article")
    tags = unique_preserve_order(tags)
    review_needed = metadata.get("source") == "fallback" or not data["title"] or (not data["authors"] and not data["venue"])
    if review_needed and "metadata-review" not in tags:
        tags.append("metadata-review")
    if not review_needed and "metadata-review" in tags:
        tags = [tag for tag in tags if tag != "metadata-review"]
    if note_is_stub_text(data, "") and "needs-summary" not in tags:
        tags.append("needs-summary")
    data["tags"] = unique_preserve_order(tags)
    return data


def note_is_stub_text(frontmatter: dict[str, Any], body: str) -> bool:
    status = normalize_space(str(frontmatter.get("status") or "")).lower()
    tags = set(str(tag) for tag in ensure_list(frontmatter.get("tags")))
    if status == "imported-metadata" or "metadata-review" in tags:
        return True
    return len(body.split()) < 200 and "needs-summary" in tags


def refresh_note_file(
    note_path: Path,
    pdf_path: Path,
    spec: CollectionSpec,
    metadata: dict[str, Any],
    folder_map: dict[str, str],
    extra_aliases: list[str] | None = None,
) -> bool:
    original_text = note_path.read_text(errors="ignore")
    frontmatter, body = parse_frontmatter(original_text)
    merged = merge_frontmatter(frontmatter, metadata, spec, pdf_path.name, pdf_path.stem)
    if extra_aliases:
        ensure_aliases(merged, *extra_aliases)
    body = repair_pdf_links(body, folder_map)
    body = repair_broken_self_pdf_links(body, spec, pdf_path.name)
    body = normalize_note_heading(body, str(merged["title"]))

    is_stub = note_is_stub_text(frontmatter, body)
    if is_stub:
        body = upsert_section(body, "Metadata Status", build_metadata_status_lines(metadata))
        body = upsert_section(body, "Basic Information", build_basic_information_lines(metadata, spec, pdf_path.name))
        abstract = normalize_space(str(metadata.get("abstract") or ""))
        if abstract:
            body = upsert_section(body, "Abstract / Extracted Summary", abstract)
        elif not get_section(body, "Abstract / Extracted Summary"):
            body = upsert_section(body, "Abstract / Extracted Summary", "")
        if not get_section(body, "Notes"):
            body = upsert_section(body, "Notes", "- ")
    else:
        abstract = normalize_space(str(metadata.get("abstract") or ""))
        current_abstract = get_section(body, "Abstract / Extracted Summary")
        if abstract and (not current_abstract or current_abstract == "-"):
            body = upsert_section(body, "Abstract / Extracted Summary", abstract)

    rebuilt = dump_frontmatter(merged) + body.rstrip() + "\n"
    if rebuilt != original_text:
        note_path.write_text(rebuilt)
        return True
    return False


def build_new_note(metadata: dict[str, Any], pdf_path: Path, spec: CollectionSpec) -> str:
    frontmatter = merge_frontmatter({}, metadata, spec, pdf_path.name, pdf_path.stem)
    frontmatter["status"] = "imported-metadata"
    tags = [str(tag) for tag in ensure_list(frontmatter.get("tags"))]
    if "needs-summary" not in tags:
        tags.append("needs-summary")
    frontmatter["tags"] = unique_preserve_order(tags)
    abstract = normalize_space(str(metadata.get("abstract") or ""))
    body_parts = [
        f"# {frontmatter['title']}",
        "",
        "## Metadata Status",
        build_metadata_status_lines(metadata),
        "",
        "## Basic Information",
        build_basic_information_lines(metadata, spec, pdf_path.name),
        "",
        "## Abstract / Extracted Summary",
        abstract,
        "",
        "## Notes",
        "- ",
        "",
    ]
    return dump_frontmatter(frontmatter) + "\n".join(body_parts)


def note_metadata_for_relations(note_path: Path) -> dict[str, Any]:
    frontmatter, _ = load_note(note_path)
    return {
        "stem": note_path.stem,
        "title": normalize_space(str(frontmatter.get("title") or "")),
        "authors": [normalize_space(str(author)) for author in ensure_list(frontmatter.get("authors")) if normalize_space(str(author))],
        "keywords": [normalize_space(str(keyword)) for keyword in ensure_list(frontmatter.get("keywords")) if normalize_space(str(keyword))],
        "topics": [normalize_space(str(topic)) for topic in ensure_list(frontmatter.get("topics")) if normalize_space(str(topic))],
        "methods": [normalize_space(str(method)) for method in ensure_list(frontmatter.get("methods")) if normalize_space(str(method))],
        "regions": [normalize_space(str(region)) for region in ensure_list(frontmatter.get("regions")) if normalize_space(str(region))],
        "journal_abbr": normalize_space(str(frontmatter.get("journal_abbr") or "")).lower(),
    }


def relation_signature(item: dict[str, Any]) -> dict[str, Any]:
    author_keys = {first_author_slug(author) for author in item["authors"] if first_author_slug(author)}
    keyword_tokens = set()
    for field in item["keywords"] + item["topics"]:
        keyword_tokens.update(token for token in slugify(field).split("_") if len(token) >= 4 and token not in STOPWORDS)
    keyword_tokens |= significant_title_tokens(item["title"])
    return {
        "authors": author_keys,
        "regions": {slugify(region) for region in item["regions"]},
        "methods": {slugify(method) for method in item["methods"]},
        "tokens": keyword_tokens,
        "journal_abbr": item["journal_abbr"],
    }


def relation_score(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, list[str]]:
    sig_a = relation_signature(a)
    sig_b = relation_signature(b)
    reasons: list[str] = []
    score = 0.0
    shared_authors = sig_a["authors"] & sig_b["authors"]
    if shared_authors:
        score += 1.6
        reasons.append("shared author")
    shared_regions = sig_a["regions"] & sig_b["regions"]
    if shared_regions:
        score += 1.1
        reasons.extend(sorted(shared_regions)[:2])
    shared_methods = sig_a["methods"] & sig_b["methods"]
    if shared_methods:
        score += 0.8
        reasons.extend(sorted(shared_methods)[:2])
    shared_tokens = sorted((sig_a["tokens"] & sig_b["tokens"]) - STOPWORDS)
    if shared_tokens:
        score += min(1.4, 0.28 * len(shared_tokens))
        reasons.extend(shared_tokens[:3])
    if sig_a["journal_abbr"] and sig_a["journal_abbr"] == sig_b["journal_abbr"]:
        score += 0.35
        reasons.append(sig_a["journal_abbr"])
    return score, unique_preserve_order(reasons)


def note_link(spec: CollectionSpec, stem: str, title: str) -> str:
    return f"[[{NOTES_FOLDER_NAME}/{spec.note_dir}/{stem}|{title}]]"


def update_related_sections(spec: CollectionSpec) -> int:
    note_paths = list_source_notes(spec.note_path)
    note_items = {stem: note_metadata_for_relations(path) for stem, path in note_paths.items()}
    updates = 0
    for stem, item in note_items.items():
        candidates: list[tuple[float, str, list[str]]] = []
        for other_stem, other_item in note_items.items():
            if other_stem == stem:
                continue
            score, reasons = relation_score(item, other_item)
            if score >= 1.2:
                candidates.append((score, other_stem, reasons))
        candidates.sort(key=lambda row: (-row[0], row[1]))
        bullets: list[str] = []
        for _, other_stem, reasons in candidates[:5]:
            other_item = note_items[other_stem]
            reason_text = ", ".join(reason.replace("_", " ") for reason in reasons[:3])
            if reason_text:
                bullets.append(f"- {note_link(spec, other_stem, other_item['title'])}  | shared: {reason_text}")
            else:
                bullets.append(f"- {note_link(spec, other_stem, other_item['title'])}")
        body_text = "\n".join(bullets) if bullets else "- "
        note_path = note_paths[stem]
        original = note_path.read_text(errors="ignore")
        frontmatter, body = parse_frontmatter(original)
        updated_body = upsert_section(body, "Related Literature", body_text)
        rebuilt = dump_frontmatter(frontmatter) + updated_body.rstrip() + "\n"
        if rebuilt != original:
            note_path.write_text(rebuilt)
            updates += 1
    return updates


def write_folder_info(spec: CollectionSpec, pdf_count: int, note_count: int, review_count: int) -> None:
    body = [
        "---",
        "type: folder-note",
        f'title: "{spec.category}"',
        f'collection: "{spec.category}"',
        f'pdf_folder: "{spec.pdf_dir}"',
        f'note_folder: "{spec.note_dir}"',
        f"pdf_count: {pdf_count}",
        f"reading_note_count: {note_count}",
        f"metadata_review_count: {review_count}",
        f'updated: "{TODAY}"',
        "---",
        f"# {spec.category}",
        "",
        "## Collection Snapshot",
        f"- PDF folder: `{spec.pdf_dir}`",
        f"- Notes folder: `{NOTES_FOLDER_NAME}/{spec.note_dir}`",
        f"- Bibliography: `{REFERENCE_ROOT.name}/{spec.bib_name}`",
        f"- PDFs: {pdf_count}",
        f"- Notes: {note_count}",
        f"- Metadata-review notes: {review_count}",
        "",
        "## Notes",
        "- This file is a folder-level index for the synced collection.",
        "",
    ]
    (spec.pdf_path / "_folder_info.md").write_text("\n".join(body))


def write_bibliography(spec: CollectionSpec) -> None:
    entries: list[str] = []
    note_paths = list_source_notes(spec.note_path)
    for pdf_path in sorted(spec.pdf_path.glob("*.pdf")):
        note_path = note_paths.get(pdf_path.stem)
        if note_path and note_path.exists():
            frontmatter, _ = load_note(note_path)
            metadata = {
                "title": frontmatter.get("title") or pdf_path.stem.replace("_", " "),
                "authors": ensure_list(frontmatter.get("authors")),
                "year": frontmatter.get("year") or "",
                "venue": frontmatter.get("venue") or "",
                "journal_abbr": frontmatter.get("journal_abbr") or "",
                "doi": frontmatter.get("doi") or "",
                "url": frontmatter.get("url") or "",
                "entry_type": note_entry_type(frontmatter, spec.category),
            }
        else:
            metadata = {
                "title": pdf_path.stem.replace("_", " "),
                "authors": [],
                "year": "",
                "venue": "",
                "journal_abbr": "",
                "doi": "",
                "url": "",
                "entry_type": note_entry_type({}, spec.category),
            }
        entries.append(build_bib_entry(pdf_path.stem, metadata, pdf_path, spec.category))
    spec.bib_path.parent.mkdir(parents=True, exist_ok=True)
    spec.bib_path.write_text("\n\n".join(entries) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def normalize_pdf_filenames(
    spec: CollectionSpec,
    resolver: MetadataResolver,
    folder_map: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, list[str]]]:
    note_paths = list_source_notes(spec.note_path)
    hash_cache: dict[Path, str] = {}
    rename_rows: list[dict[str, Any]] = []
    archive_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    alias_map: dict[str, list[str]] = {}

    pdf_paths = sorted(
        spec.pdf_path.glob("*.pdf"),
        key=lambda path: (
            0 if looks_standardized_stem(strip_copy_suffix(path.stem)) else 1,
            0 if path.stem in note_paths else 1,
            len(path.name),
            path.name.lower(),
        ),
    )

    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            continue
        note_path = note_paths.get(pdf_path.stem)
        note_data = load_note(note_path)[0] if note_path and note_path.exists() else None
        should_resolve = (
            not looks_standardized_stem(strip_copy_suffix(pdf_path.stem))
            or bool(parse_stem(pdf_path.stem)["copy_suffix"])
            or note_path is None
            or note_is_stub(note_path)
        )
        if should_resolve:
            metadata = resolver.resolve_metadata(pdf_path, spec, note_data)
        else:
            metadata = resolver.normalize_note_metadata(note_data or {}, spec.category)
        desired_stem = build_desired_stem(pdf_path.stem, metadata)
        desired_path = spec.pdf_path / f"{desired_stem}.pdf"
        current_stem = pdf_path.stem

        if desired_path == pdf_path:
            continue

        if desired_path.exists():
            target_note = note_paths.get(desired_path.stem)
            if files_identical(pdf_path, desired_path, hash_cache):
                if duplicate_note_safe(note_path, target_note):
                    archived_path = archive_duplicate_pdf(pdf_path, spec)
                    archive_rows.append(
                        {
                            "collection": spec.pdf_dir,
                            "original_path": str(pdf_path),
                            "archived_path": str(archived_path),
                            "primary_path": str(desired_path),
                            "reason": "exact_duplicate",
                        }
                    )
                    alias_map.setdefault(desired_path.stem, []).append(current_stem)
                    continue
                review_rows.append(
                    {
                        "collection": spec.pdf_dir,
                        "pdf_path": str(pdf_path),
                        "conflict_path": str(desired_path),
                        "reason": "duplicate_pdf_with_two_non_stub_notes",
                    }
                )
                continue

            unique_path = next_available_pdf_path(spec.pdf_path, desired_stem, pdf_path)
            if unique_path != pdf_path:
                pdf_path.rename(unique_path)
                rename_rows.append(
                    {
                        "collection": spec.pdf_dir,
                        "old_path": str(pdf_path),
                        "new_path": str(unique_path),
                        "reason": "normalized_with_suffix",
                    }
                )
                alias_map.setdefault(unique_path.stem, []).append(current_stem)
            continue

        pdf_path.rename(desired_path)
        rename_rows.append(
            {
                "collection": spec.pdf_dir,
                "old_path": str(pdf_path),
                "new_path": str(desired_path),
                "reason": "normalized_name",
            }
        )
        alias_map.setdefault(desired_path.stem, []).append(current_stem)

    return rename_rows, archive_rows, review_rows, alias_map


def sync_collection(spec: CollectionSpec, resolver: MetadataResolver, folder_map: dict[str, str]) -> dict[str, Any]:
    spec.note_path.mkdir(parents=True, exist_ok=True)
    rename_rows, archive_rows, review_rows, alias_map = normalize_pdf_filenames(spec, resolver, folder_map)

    note_paths = list_source_notes(spec.note_path)
    for new_stem, aliases in alias_map.items():
        for old_stem in aliases:
            old_note = spec.note_path / f"{old_stem}.md"
            new_note = spec.note_path / f"{new_stem}.md"
            if old_note.exists() and old_note != new_note:
                merge_note_files(new_note, old_note, new_stem, old_stem)

    note_paths = list_source_notes(spec.note_path)
    created_notes = 0
    updated_notes = 0

    for pdf_path in sorted(spec.pdf_path.glob("*.pdf")):
        note_path = note_paths.get(pdf_path.stem)
        note_data = load_note(note_path)[0] if note_path and note_path.exists() else None
        needs_resolution = (
            note_path is None
            or note_is_stub(note_path)
            or not note_data
            or not note_data.get("doi")
            or not note_data.get("venue")
            or not ensure_list(note_data.get("authors"))
        )
        metadata = resolver.resolve_metadata(pdf_path, spec, note_data) if needs_resolution else resolver.normalize_note_metadata(note_data, spec.category)
        current_aliases = alias_map.get(pdf_path.stem, [])
        if note_path and note_path.exists():
            if refresh_note_file(note_path, pdf_path, spec, metadata, folder_map, current_aliases):
                updated_notes += 1
        else:
            new_note_path = spec.note_path / f"{pdf_path.stem}.md"
            new_note_path.write_text(build_new_note(metadata, pdf_path, spec))
            if current_aliases:
                refresh_note_file(new_note_path, pdf_path, spec, metadata, folder_map, current_aliases)
            created_notes += 1

    related_updates = update_related_sections(spec)
    write_bibliography(spec)

    note_paths = list_source_notes(spec.note_path)
    metadata_review_count = 0
    for note_path in note_paths.values():
        frontmatter, _ = load_note(note_path)
        tags = set(str(tag) for tag in ensure_list(frontmatter.get("tags")))
        if "metadata-review" in tags:
            metadata_review_count += 1

    write_folder_info(spec, len(list(spec.pdf_path.glob("*.pdf"))), len(note_paths), metadata_review_count)

    return {
        "collection": spec.pdf_dir,
        "category": spec.category,
        "pdf_count": len(list(spec.pdf_path.glob("*.pdf"))),
        "note_count": len(note_paths),
        "created_notes": created_notes,
        "updated_notes": updated_notes,
        "related_updates": related_updates,
        "metadata_review_count": metadata_review_count,
        "rename_rows": rename_rows,
        "archive_rows": archive_rows,
        "review_rows": review_rows,
        "bib_path": str(spec.bib_path),
    }


def clean_zero_byte_duplicate_notes() -> int:
    removed = 0
    if not NOTES_ROOT.exists():
        return removed
    for note_path in NOTES_ROOT.glob("*/*.md"):
        if note_path.name.startswith("_"):
            continue
        if note_path.stat().st_size != 0:
            continue
        note_path.unlink()
        removed += 1
    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--collection",
        action="append",
        help="Process only a specific PDF folder, note folder, or category name.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    filters = set(args.collection or []) or None
    NOTES_ROOT.mkdir(parents=True, exist_ok=True)
    REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    removed_zero_byte = clean_zero_byte_duplicate_notes()
    collections = discover_collections(filters)
    folder_map = build_pdf_folder_map(collections)
    abbr_map = build_abbr_map(collections)
    resolver = MetadataResolver(abbr_map)

    summaries: list[dict[str, Any]] = []
    rename_rows: list[dict[str, Any]] = []
    archive_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []

    for spec in collections:
        summary = sync_collection(spec, resolver, folder_map)
        summaries.append(summary)
        rename_rows.extend(summary["rename_rows"])
        archive_rows.extend(summary["archive_rows"])
        review_rows.extend(summary["review_rows"])
        print(
            f"{spec.pdf_dir}: pdfs={summary['pdf_count']}, notes={summary['note_count']}, "
            f"created={summary['created_notes']}, updated={summary['updated_notes']}, "
            f"review={summary['metadata_review_count']}"
        )

    write_csv(
        REPORT_ROOT / "literature_pdf_rename_manifest.csv",
        rename_rows,
        ["collection", "old_path", "new_path", "reason"],
    )
    write_csv(
        REPORT_ROOT / "literature_pdf_duplicate_archive_manifest.csv",
        archive_rows,
        ["collection", "original_path", "archived_path", "primary_path", "reason"],
    )
    write_csv(
        REPORT_ROOT / "literature_pdf_duplicate_review.csv",
        review_rows,
        ["collection", "pdf_path", "conflict_path", "reason"],
    )

    print(f"Zero-byte notes removed: {removed_zero_byte}")
    print(f"Collections processed: {len(summaries)}")
    print(f"Renamed PDFs: {len(rename_rows)}")
    print(f"Archived duplicate PDFs: {len(archive_rows)}")
    print(f"Duplicate review items: {len(review_rows)}")


if __name__ == "__main__":
    main()
