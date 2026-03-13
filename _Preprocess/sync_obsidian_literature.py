#!/usr/bin/env python3
from __future__ import annotations

import html
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests
import yaml
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
READING_ROOT = ROOT / "Reading Notes"
REFERENCE_ROOT = ROOT / "reference"
TODAY = "2026-03-13"
USER_AGENT = "Codex Literature Vault Sync/1.0 (mailto:no-reply@example.com)"
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
DOUBLE_SUFFIX_RE = re.compile(
    r"^(?P<base>.+)_(?P<abbr>[a-z0-9]+)_(?P=abbr)(?P<ext>\.md)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CollectionSpec:
    old_pdf_dir: str
    canonical_name: str
    bib_name: str
    note_dir: str


COLLECTIONS = [
    CollectionSpec("Authoritarianism", "Authoritarian Politics", "authoritarian_politics.bib", "Authoritarian Politics"),
    CollectionSpec(
        "Bureaucracy",
        "Developing Country Bureaucracy and Accountability",
        "developing_country_bureaucracy_accountability.bib",
        "Developing Country Bureaucracy and Accountability",
    ),
    CollectionSpec("Dissertation", "Good Dissertation", "good_dissertation.bib", "Good Dissertation"),
    CollectionSpec(
        "Information",
        "China Censorship Propaganda and Public Opinion",
        "china_censorship_propaganda_and_public_opinion.bib",
        "China Censorship Propaganda and Public Opinion",
    ),
    CollectionSpec("Law", "Lawyers and Courts", "lawyers_and_courts.bib", "Lawyers and Courts"),
    CollectionSpec("Method", "Method", "method.bib", "Method"),
    CollectionSpec("RCT", "RCT", "rct.bib", "RCT"),
]

OLD_TO_CANONICAL = {spec.old_pdf_dir: spec.canonical_name for spec in COLLECTIONS if spec.old_pdf_dir != spec.canonical_name}


KNOWN_JOURNALS = {
    "a": "Administration",
    "aejapplied": "American Economic Journal: Applied Economics",
    "aejeconomicpolicy": "American Economic Journal: Economic Policy",
    "aejmacro": "American Economic Journal: Macroeconomics",
    "aejmicro": "American Economic Journal: Microeconomics",
    "ajls": "Asian Journal of Law and Society",
    "ajps": "American Journal of Political Science",
    "apsr": "American Political Science Review",
    "arps": "Annual Review of Political Science",
    "arlss": "Annual Review of Law and Social Science",
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
    "restud": "Review of Economic Studies",
    "uchicago": "University of Chicago",
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
    re.compile(pat, re.IGNORECASE)
    for pat in [
        r"^american political science review$",
        r"^political science research and methods",
        r"^the journal of politics$",
        r"^american economic review$",
        r"^mit open access articles$",
        r"^uc berkeley$",
        r"^uc berkeley previously published works$",
        r"^eScholarship\.org$",
        r"^cadmus",
        r"^disclaimer",
        r"^department of",
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
    ]
]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "collection"


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).strip().lower()
    return text


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    data = yaml.safe_load(raw) or {}
    body = text[match.end() :]
    return data, body


def dump_frontmatter(data: dict[str, Any]) -> str:
    raw = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False).strip()
    return f"---\n{raw}\n---\n"


def list_source_notes(note_dir: Path) -> dict[str, Path]:
    notes: dict[str, Path] = {}
    if not note_dir.exists():
        return notes
    for path in sorted(note_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        if path.stat().st_size == 0:
            continue
        notes[path.stem] = path
    return notes


def rename_collection_folders() -> list[tuple[str, str]]:
    renames: list[tuple[str, str]] = []
    for spec in COLLECTIONS:
        src = ROOT / spec.old_pdf_dir
        dst = ROOT / spec.canonical_name
        if not src.exists():
            continue
        if src.samefile(dst) if dst.exists() else False:
            continue
        if src.name == spec.canonical_name:
            continue
        src.rename(dst)
        renames.append((spec.old_pdf_dir, spec.canonical_name))
    return renames


def clean_zero_byte_duplicates() -> list[Path]:
    removed: list[Path] = []
    for note_dir in READING_ROOT.glob("*"):
        if not note_dir.is_dir():
            continue
        for note_path in note_dir.glob("*.md"):
            if note_path.stat().st_size != 0:
                continue
            match = DOUBLE_SUFFIX_RE.match(note_path.name)
            if not match:
                continue
            canonical = note_dir / f"{match.group('base')}_{match.group('abbr')}.md"
            if canonical.exists() and canonical.stat().st_size > 0:
                note_path.unlink()
                removed.append(note_path)
    return removed


def canonicalize_link_path(path_text: str) -> str:
    raw = path_text.replace("\\", "/")
    if not raw.endswith(".md"):
        return raw
    link_path = ROOT / raw
    if link_path.exists():
        return raw
    parts = raw.rsplit("/", 1)
    if len(parts) != 2:
        return raw
    parent, filename = parts
    match = DOUBLE_SUFFIX_RE.match(filename)
    if not match:
        fixed = best_fuzzy_note_match(parent, Path(filename).stem)
        return f"{parent}/{fixed}.md" if fixed else raw
    fixed = f"{match.group('base')}_{match.group('abbr')}"
    if (ROOT / parent / f"{fixed}.md").exists():
        return f"{parent}/{fixed}.md"
    fuzzy = best_fuzzy_note_match(parent, Path(filename).stem)
    if fuzzy:
        return f"{parent}/{fuzzy}.md"
    return raw


def repair_note_links(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        parts = inner.split("|", 1)
        target = parts[0]
        fixed = canonicalize_link_path(target)
        if fixed == target:
            return match.group(0)
        if len(parts) == 2:
            return f"[[{fixed}|{parts[1]}]]"
        return f"[[{fixed}]]"

    return re.sub(r"\[\[([^\]]+)\]\]", repl, text)


def best_fuzzy_note_match(parent: str, missing_stem: str) -> str | None:
    parent_dir = ROOT / parent
    if not parent_dir.exists():
        return None
    parsed_missing = parse_stem(missing_stem)
    candidates = []
    for path in parent_dir.glob("*.md"):
        if path.name.startswith("_") or path.stat().st_size == 0:
            continue
        parsed_candidate = parse_stem(path.stem)
        if parsed_missing["author"] and parsed_candidate["author"] and parsed_candidate["author"] != parsed_missing["author"]:
            continue
        if parsed_missing["year"] and parsed_candidate["year"] and parsed_candidate["year"] != parsed_missing["year"]:
            continue
        candidates.append(path.stem)
    if not candidates:
        return None
    best_stem = ""
    best_score = 0.0
    for stem in candidates:
        score = SequenceMatcher(None, missing_stem, stem).ratio()
        if score > best_score:
            best_stem = stem
            best_score = score
    return best_stem if best_score >= 0.74 else None


def repair_pdf_links(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        folder = match.group(1)
        filename = match.group(2)
        canonical = OLD_TO_CANONICAL.get(folder, folder)
        return f"[[{canonical}/{filename}]]"

    return re.sub(r"\[\[([^/\]]+)/([^/\]]+\.pdf)\]\]", repl, text)


def replace_or_insert_frontmatter_line(frontmatter: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(key)}:.*$")
    replacement = f'{key}: "{value}"'
    if pattern.search(frontmatter):
        return pattern.sub(replacement, frontmatter, count=1)
    lines = frontmatter.splitlines()
    if lines and lines[-1].strip():
        lines.append(replacement)
    else:
        lines.insert(len(lines), replacement)
    return "\n".join(lines)


def update_existing_note(note_path: Path, collection_name: str) -> bool:
    text = note_path.read_text()
    match = FRONTMATTER_RE.match(text)
    if not match:
        return False
    frontmatter = match.group(1)
    updated_frontmatter = replace_or_insert_frontmatter_line(frontmatter, "category", collection_name)
    updated_frontmatter = replace_or_insert_frontmatter_line(
        updated_frontmatter,
        "pdf_local",
        f"[[{collection_name}/{note_path.stem}.pdf]]",
    )
    rebuilt = f"---\n{updated_frontmatter}\n---\n{text[match.end():]}"
    rebuilt = repair_note_links(rebuilt)
    rebuilt = repair_pdf_links(rebuilt)
    if rebuilt != text:
        note_path.write_text(rebuilt)
        return True
    return False


def load_note_metadata(note_path: Path) -> dict[str, Any]:
    text = note_path.read_text()
    frontmatter, _ = parse_frontmatter(text)
    frontmatter["__path"] = str(note_path)
    frontmatter["__stem"] = note_path.stem
    return frontmatter


def build_abbr_map() -> dict[str, str]:
    abbr_map = dict(KNOWN_JOURNALS)
    for note_dir in READING_ROOT.glob("*"):
        if not note_dir.is_dir():
            continue
        for note_path in note_dir.glob("*.md"):
            if note_path.name.startswith("_") or note_path.stat().st_size == 0:
                continue
            try:
                data = load_note_metadata(note_path)
            except Exception:
                continue
            abbr = normalize_space(str(data.get("journal_abbr") or "")).lower()
            venue = normalize_space(str(data.get("venue") or ""))
            if abbr and venue:
                abbr_map.setdefault(abbr, venue)
    return abbr_map


def parse_stem(stem: str) -> dict[str, str]:
    tokens = stem.split("_")
    copy_suffix = ""
    if len(tokens) >= 2 and tokens[-1].isdigit() and len(tokens[-1]) <= 2:
        copy_suffix = tokens.pop()
    year = ""
    year_index = -1
    for i, token in enumerate(tokens):
        if re.fullmatch(r"(19|20)\d{2}", token):
            year = token
            year_index = i
            break
    author = tokens[0] if tokens else ""
    abbr = tokens[year_index + 1] if year and year_index + 1 < len(tokens) else ""
    return {
        "author": author,
        "year": year,
        "abbr": abbr,
        "copy_suffix": copy_suffix,
    }


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


def is_plausible_title(title: str) -> bool:
    title = normalize_space(title)
    if len(title) < 12:
        return False
    if title.lower() in FALLBACK_TITLE_SKIP:
        return False
    letters = sum(ch.isalpha() for ch in title)
    digits = sum(ch.isdigit() for ch in title)
    if letters < 8:
        return False
    if digits > letters:
        return False
    return True


def title_from_pdf_metadata(pdf_path: Path) -> tuple[str, str]:
    try:
        reader = PdfReader(str(pdf_path))
        metadata = reader.metadata or {}
        title = normalize_space(str(metadata.get("/Title") or ""))
        author = normalize_space(str(metadata.get("/Author") or ""))
        return title, author
    except Exception:
        return "", ""


def title_from_text(text: str) -> str:
    lines = [normalize_space(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    for idx, line in enumerate(lines):
        if line.lower() == "title":
            collected: list[str] = []
            for candidate in lines[idx + 1 : idx + 6]:
                lower = candidate.lower()
                if lower in FALLBACK_TITLE_SKIP:
                    break
                if candidate.startswith("http"):
                    break
                if len(candidate) > 160:
                    break
                if re.match(r"^[A-Z][a-z]+, [A-Z]", candidate):
                    break
                collected.append(candidate)
                if candidate.endswith("."):
                    break
            joined = normalize_space(" ".join(collected))
            if is_plausible_title(joined):
                return joined.rstrip(".")
    candidates: list[str] = []
    for line in lines[:40]:
        lower = line.lower()
        if lower in FALLBACK_TITLE_SKIP:
            continue
        if any(pattern.search(line) for pattern in BOILERPLATE_PATTERNS):
            continue
        if line.startswith("http") or "@" in line:
            continue
        if DOI_RE.search(line):
            continue
        if re.search(r"^(vol\.|volume|issue|may|june|july|august|september|october|november|december|january|february|march|april)\b", lower):
            continue
        if len(line) < 12 or len(line) > 180:
            continue
        candidates.append(line)
    if not candidates:
        return ""
    for i, line in enumerate(candidates):
        if is_plausible_title(line):
            pieces = [line]
            for nxt in candidates[i + 1 : i + 4]:
                if len(normalize_space(" ".join(pieces + [nxt]))) > 180:
                    break
                if re.match(r"^[A-Z][A-Z .'-]+$", nxt):
                    break
                if re.match(r"^[A-Z][a-z]+(?: [A-Z][a-z]+)+$", nxt):
                    break
                if any(tok in nxt.lower() for tok in ["university", "department", "abstract", "received", "published"]):
                    break
                if nxt.endswith(","):
                    break
                if nxt[0].islower():
                    pieces.append(nxt)
                    continue
                if len(nxt.split()) <= 12 and not nxt.isupper():
                    pieces.append(nxt)
            joined = normalize_space(" ".join(pieces)).rstrip(".")
            if is_plausible_title(joined):
                return joined
    return ""


def author_list_from_crossref(message: dict[str, Any]) -> list[str]:
    authors = []
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
    type_name = (message.get("type") or "").lower()
    if type_name == "journal-article":
        return "article"
    if type_name == "book":
        return "book"
    if type_name == "book-chapter":
        return "incollection"
    if type_name == "dissertation" or collection_name == "Good Dissertation":
        return "phdthesis"
    if type_name == "report":
        return "techreport"
    return "misc"


def note_entry_type(metadata: dict[str, Any], collection_name: str) -> str:
    if collection_name == "Good Dissertation":
        return "phdthesis"
    venue = normalize_space(str(metadata.get("venue") or ""))
    abbr = normalize_space(str(metadata.get("journal_abbr") or "")).lower()
    if abbr:
        return "article"
    if venue and any(token in venue.lower() for token in ["university", "school", "uchicago", "mit", "harvard", "stanford", "princeton"]):
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
    author_value = " and ".join(normalize_space(str(a)) for a in authors if normalize_space(str(a)))
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
        mapped_name = "number" if field_name == "issue" else field_name
        fields.append((mapped_name, value))
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
        query_parts = [title, author_token, year, venue]
        query = " ".join(part for part in query_parts if part)
        if not query.strip():
            self.search_cache[cache_key] = None
            return None
        params = {"query.bibliographic": query, "rows": 8, "select": "DOI,title,author,container-title,type,URL,page,volume,issue,published-print,published-online,published,issued,publisher,abstract"}
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
        return {
            "title": normalize_space(((message.get("title") or [""])[0])),
            "authors": author_list_from_crossref(message),
            "year": year_from_crossref(message),
            "venue": venue,
            "journal_abbr": default_abbr or "",
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

    def metadata_from_openalex(self, item: dict[str, Any], default_abbr: str) -> dict[str, Any]:
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
        return {
            "title": normalize_space(str(item.get("display_name") or "")),
            "authors": authors,
            "year": str(item.get("publication_year") or ""),
            "venue": venue,
            "journal_abbr": default_abbr or "",
            "doi": doi,
            "url": normalize_space(str((item.get("ids") or {}).get("doi") or (f"https://doi.org/{doi}" if doi else ""))),
            "abstract": "",
            "volume": normalize_space(str(biblio.get("volume") or "")),
            "issue": normalize_space(str(biblio.get("issue") or "")),
            "pages": pages,
            "publisher": "",
            "entry_type": "article" if venue else "misc",
            "source": "openalex",
        }

    def fallback_metadata(self, pdf_path: Path, collection_name: str, parsed: dict[str, str]) -> dict[str, Any]:
        pdf_title, pdf_author = title_from_pdf_metadata(pdf_path)
        text = extract_pdf_text(pdf_path)
        doi = extract_doi(pdf_title, text)
        if doi:
            message = self.crossref_by_doi(doi)
            if message:
                return self.metadata_from_crossref(message, parsed["abbr"], collection_name)
        title = pdf_title if is_plausible_title(pdf_title) else title_from_text(text)
        venue = self.abbr_map.get(parsed["abbr"], "")
        if title:
            message = self.crossref_search(title, parsed["year"], parsed["author"], venue)
            if message:
                return self.metadata_from_crossref(message, parsed["abbr"], collection_name)
            item = self.openalex_search(title, parsed["year"])
            if item:
                return self.metadata_from_openalex(item, parsed["abbr"])
        authors = [pdf_author] if normalize_space(pdf_author) else []
        if not title:
            title = normalize_space(pdf_path.stem.replace("_", " "))
        note = "Metadata inferred from local PDF; review recommended."
        return {
            "title": title,
            "authors": authors,
            "year": parsed["year"],
            "venue": venue,
            "journal_abbr": parsed["abbr"],
            "doi": doi,
            "url": f"https://doi.org/{doi}" if doi else "",
            "abstract": "",
            "volume": "",
            "issue": "",
            "pages": "",
            "publisher": "",
            "entry_type": "phdthesis" if collection_name == "Good Dissertation" else ("article" if venue else "misc"),
            "note": note,
            "source": "fallback",
        }


def normalize_note_metadata(data: dict[str, Any], collection_name: str) -> dict[str, Any]:
    authors = data.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    doi = normalize_space(str(data.get("doi") or "")).lower()
    return {
        "title": normalize_space(str(data.get("title") or "")),
        "authors": [normalize_space(str(author)) for author in authors if normalize_space(str(author))],
        "year": str(data.get("year") or ""),
        "venue": normalize_space(str(data.get("venue") or "")),
        "journal_abbr": normalize_space(str(data.get("journal_abbr") or "")).lower(),
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


def build_new_note(metadata: dict[str, Any], pdf_path: Path, collection_name: str) -> str:
    tags = ["literature", "source-note", slugify(collection_name), "needs-summary"]
    if metadata.get("source") == "fallback":
        tags.append("metadata-review")
    title = metadata["title"]
    authors = metadata.get("authors") or []
    abstract = normalize_space(str(metadata.get("abstract") or ""))
    frontmatter = {
        "type": "source-note",
        "title": title,
        "aliases": [pdf_path.stem],
        "authors": authors,
        "year": int(metadata["year"]) if str(metadata.get("year") or "").isdigit() else metadata.get("year") or "",
        "venue": metadata.get("venue") or "",
        "category": collection_name,
        "topics": [],
        "keywords": [],
        "methods": [],
        "regions": [],
        "journal_abbr": metadata.get("journal_abbr") or "",
        "cases": [],
        "projects": [],
        "status": "imported-metadata",
        "priority": "medium",
        "rating": None,
        "pdf_local": f"[[{collection_name}/{pdf_path.name}]]",
        "doi": metadata.get("doi") or "",
        "url": metadata.get("url") or "",
        "zotero_key": "",
        "date_added": TODAY,
        "last_reviewed": TODAY,
        "tags": tags,
    }
    basic_authors = ", ".join(authors) if authors else ""
    basic_doi = metadata.get("doi") or ""
    body_lines = [
        f"# {title}",
        "",
        "## Metadata Status",
        f"- Imported from local PDF and external metadata lookup on {TODAY}.",
        "- Full synthesis is still pending.",
        "",
        "## Basic Information",
        f"- Authors: {basic_authors}",
        f"- Year: {metadata.get('year') or ''}",
        f"- Venue: {metadata.get('venue') or ''}",
        f"- DOI: {basic_doi}",
        f"- PDF: [[{collection_name}/{pdf_path.name}]]",
        "",
        "## Abstract / Extracted Summary",
        abstract,
        "",
        "## Notes",
        "- ",
        "",
    ]
    return dump_frontmatter(frontmatter) + "\n".join(body_lines)


def write_folder_info(
    folder_path: Path,
    spec: CollectionSpec,
    pdf_count: int,
    note_count: int,
    review_count: int,
) -> None:
    body = [
        "---",
        "type: folder-note",
        f'title: "{spec.canonical_name}"',
        f'collection: "{spec.canonical_name}"',
        f"pdf_count: {pdf_count}",
        f"reading_note_count: {note_count}",
        f"metadata_review_count: {review_count}",
        f'updated: "{TODAY}"',
        "---",
        f"# {spec.canonical_name}",
        "",
        "## Collection Snapshot",
        f"- PDFs: {pdf_count}",
        f"- Reading notes: {note_count}",
        f"- Metadata-review notes: {review_count}",
        f"- Reference bibliography: `reference/{spec.bib_name}`",
        f"- Reading notes folder: `Reading Notes/{spec.note_dir}`",
        "",
        "## Notes",
        "- This file is a folder-level index for the collection.",
        "",
    ]
    (folder_path / "_folder_info.md").write_text("\n".join(body))


def refresh_existing_notes(spec: CollectionSpec) -> int:
    note_dir = READING_ROOT / spec.note_dir
    if not note_dir.exists():
        return 0
    updates = 0
    for note_path in sorted(note_dir.glob("*.md")):
        if note_path.name.startswith("_"):
            continue
        if note_path.stat().st_size == 0:
            continue
        if update_existing_note(note_path, spec.canonical_name):
            updates += 1
    return updates


def ensure_note_folder(note_dir: Path) -> None:
    note_dir.mkdir(parents=True, exist_ok=True)


def count_metadata_review_notes(note_dir: Path) -> int:
    count = 0
    for note_path in list_source_notes(note_dir).values():
        try:
            data = load_note_metadata(note_path)
        except Exception:
            continue
        tags = data.get("tags") or []
        if isinstance(tags, list) and "metadata-review" in tags:
            count += 1
    return count


def generate_collection_outputs(spec: CollectionSpec, resolver: MetadataResolver) -> dict[str, Any]:
    pdf_dir = ROOT / spec.canonical_name
    note_dir = READING_ROOT / spec.note_dir
    ensure_note_folder(note_dir)
    note_paths = list_source_notes(note_dir)
    note_metadata = {stem: load_note_metadata(path) for stem, path in note_paths.items()}
    created_notes = 0
    review_notes = 0
    bib_entries: list[str] = []
    resolved_cache: dict[str, dict[str, Any]] = {}
    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        stem = pdf_path.stem
        if stem in note_metadata:
            metadata = normalize_note_metadata(note_metadata[stem], spec.canonical_name)
        else:
            parsed = parse_stem(stem)
            metadata = resolver.fallback_metadata(pdf_path, spec.canonical_name, parsed)
            resolved_cache[stem] = metadata
            note_path = note_dir / f"{stem}.md"
            note_path.write_text(build_new_note(metadata, pdf_path, spec.canonical_name))
            created_notes += 1
            if metadata.get("source") == "fallback":
                review_notes += 1
        bib_entries.append(build_bib_entry(stem, metadata, pdf_path, spec.canonical_name))
    current_notes = list_source_notes(note_dir)
    review_notes = count_metadata_review_notes(note_dir)
    write_folder_info(pdf_dir, spec, len(list(pdf_dir.glob("*.pdf"))), len(current_notes), review_notes)
    bib_path = REFERENCE_ROOT / spec.bib_name
    bib_path.write_text("\n\n".join(bib_entries) + "\n")
    return {
        "pdf_count": len(list(pdf_dir.glob("*.pdf"))),
        "note_count": len(current_notes),
        "created_notes": created_notes,
        "review_notes": review_notes,
        "bib_path": str(bib_path),
    }


def main() -> None:
    REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    renames = rename_collection_folders()
    removed_duplicates = clean_zero_byte_duplicates()
    abbr_map = build_abbr_map()
    resolver = MetadataResolver(abbr_map)
    refreshed = {}
    for spec in COLLECTIONS:
        refreshed[spec.canonical_name] = refresh_existing_notes(spec)
    summaries = {}
    for spec in COLLECTIONS:
        pdf_dir = ROOT / spec.canonical_name
        if not pdf_dir.exists():
            continue
        summaries[spec.canonical_name] = generate_collection_outputs(spec, resolver)
    print("Folder renames:")
    for old, new in renames:
        print(f"  - {old} -> {new}")
    print("Removed zero-byte duplicates:")
    for path in removed_duplicates:
        print(f"  - {path}")
    print("Updated existing notes:")
    for name, count in refreshed.items():
        print(f"  - {name}: {count}")
    print("Collection summary:")
    for name, summary in summaries.items():
        print(
            f"  - {name}: pdfs={summary['pdf_count']}, notes={summary['note_count']}, "
            f"created_notes={summary['created_notes']}, metadata_review={summary['review_notes']}"
        )


if __name__ == "__main__":
    main()
