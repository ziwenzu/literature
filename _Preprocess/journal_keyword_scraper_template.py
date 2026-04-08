#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import threading
import time
import tomllib
import unicodedata
import urllib.robotparser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path("/Users/ziwenzu/Library/CloudStorage/Dropbox")
SCRIPT_DIR = Path(__file__).resolve().parent
PENDING_SOURCES_PATH = SCRIPT_DIR / "crawler_next_journals.csv"
USER_AGENT = "Mozilla/5.0 (compatible; Codex/1.0; +mailto:codex@example.com)"
REQUEST_HEADERS = {"User-Agent": USER_AGENT}


@dataclass(frozen=True)
class Source:
    code: str
    display_name: str
    openalex_source_id: str
    filename_slug: str
    publisher: str = ""
    publisher_domains: tuple[str, ...] = ()
    title_aliases: tuple[str, ...] = ()


DEFAULT_SOURCES = [
    Source(
        "APSR",
        "American Political Science Review",
        "S176007004",
        "apsr",
        publisher="Cambridge University Press",
        publisher_domains=("cambridge.org", "jstor.org"),
    ),
    Source(
        "AJPS",
        "American Journal of Political Science",
        "S90314269",
        "ajps",
        publisher="Wiley",
        publisher_domains=("onlinelibrary.wiley.com", "wiley.com"),
    ),
    Source(
        "JOP",
        "The Journal of Politics",
        "S95650557",
        "jop",
        publisher="University of Chicago Press",
        publisher_domains=("journals.uchicago.edu",),
    ),
    Source(
        "CPS",
        "Comparative Political Studies",
        "S105556297",
        "cps",
        publisher="SAGE",
        publisher_domains=("journals.sagepub.com",),
    ),
    Source(
        "QJPS",
        "Quarterly Journal of Political Science",
        "S44648735",
        "qjps",
        publisher="Now Publishers",
        publisher_domains=("nowpublishers.com",),
    ),
    Source(
        "JEPS",
        "Journal of Experimental Political Science",
        "S4210184980",
        "jeps",
        publisher="Cambridge University Press",
        publisher_domains=("cambridge.org",),
    ),
    Source(
        "CQ",
        "The China Quarterly",
        "S12189451",
        "cq",
        publisher="Cambridge University Press",
        publisher_domains=("cambridge.org", "jstor.org"),
        title_aliases=("China Quarterly",),
    ),
    Source(
        "JCC",
        "Journal of Contemporary China",
        "S102994345",
        "jcc",
        publisher="Taylor & Francis",
        publisher_domains=("tandfonline.com",),
    ),
    Source(
        "WP",
        "World Politics",
        "S143110675",
        "wp",
        publisher="Cambridge University Press",
        publisher_domains=("cambridge.org", "jstor.org"),
    ),
    Source(
        "IO",
        "International Organization",
        "S160686149",
        "io",
        publisher="Cambridge University Press",
        publisher_domains=("cambridge.org", "jstor.org"),
    ),
    Source(
        "BJPS",
        "British Journal of Political Science",
        "S95691132",
        "bjps",
        publisher="Cambridge University Press",
        publisher_domains=("cambridge.org", "jstor.org"),
    ),
    Source(
        "PAN",
        "Political Analysis",
        "S29331042",
        "pan",
        publisher="Cambridge University Press",
        publisher_domains=("cambridge.org", "academic.oup.com", "oup.com", "oxfordjournals.org"),
    ),
    Source(
        "PSRM",
        "Political Science Research and Methods",
        "S2764571748",
        "psrm",
        publisher="Cambridge University Press",
        publisher_domains=("cambridge.org",),
    ),
    Source(
        "ARPS",
        "Annual Review of Political Science",
        "S8194976",
        "arps",
        publisher="Annual Reviews",
        publisher_domains=("annualreviews.org",),
    ),
    Source(
        "AER",
        "American Economic Review",
        "S23254222",
        "aer",
        publisher="American Economic Association",
        publisher_domains=("aeaweb.org",),
    ),
    Source(
        "AEJAPPLIED",
        "American Economic Journal: Applied Economics",
        "S42893225",
        "aejapplied",
        publisher="American Economic Association",
        publisher_domains=("aeaweb.org",),
    ),
    Source(
        "AEJPOLICY",
        "American Economic Journal: Economic Policy",
        "S158011328",
        "aejpolicy",
        publisher="American Economic Association",
        publisher_domains=("aeaweb.org",),
    ),
    Source(
        "AEJMACRO",
        "American Economic Journal: Macroeconomics",
        "S170166683",
        "aejmacro",
        publisher="American Economic Association",
        publisher_domains=("aeaweb.org",),
    ),
    Source(
        "AEJMICRO",
        "American Economic Journal: Microeconomics",
        "S96919139",
        "aejmicro",
        publisher="American Economic Association",
        publisher_domains=("aeaweb.org",),
    ),
    Source(
        "AEJINSIGHTS",
        "American Economic Review Insights",
        "S4210174288",
        "aejinsights",
        publisher="American Economic Association",
        publisher_domains=("aeaweb.org",),
    ),
    Source(
        "JPE",
        "Journal of Political Economy",
        "S95323914",
        "jpe",
        publisher="University of Chicago Press",
        publisher_domains=("journals.uchicago.edu",),
    ),
    Source(
        "JPUBECO",
        "Journal of Public Economics",
        "S199447588",
        "jpubeco",
        publisher="Elsevier",
        publisher_domains=("sciencedirect.com", "elsevier.com"),
        title_aliases=("Journal of Public Economics",),
    ),
    Source(
        "JDE",
        "Journal of Development Economics",
        "S101209419",
        "jde",
        publisher="Elsevier",
        publisher_domains=("sciencedirect.com", "elsevier.com"),
    ),
    Source(
        "ECONOMETRICA",
        "Econometrica",
        "S95464858",
        "econometrica",
        publisher="Wiley",
        publisher_domains=("onlinelibrary.wiley.com", "wiley.com"),
    ),
    Source(
        "QJE",
        "The Quarterly Journal of Economics",
        "S203860005",
        "qje",
        publisher="Oxford University Press",
        publisher_domains=("academic.oup.com",),
        title_aliases=("Quarterly Journal of Economics",),
    ),
    Source(
        "RESTUD",
        "The Review of Economic Studies",
        "S88935262",
        "restud",
        publisher="Oxford University Press",
        publisher_domains=("academic.oup.com",),
        title_aliases=("Review of Economic Studies",),
    ),
    Source(
        "RESTAT",
        "The Review of Economics and Statistics",
        "S180061323",
        "restat",
        publisher="MIT Press",
        publisher_domains=("direct.mit.edu", "mitpressjournals.org"),
        title_aliases=("Review of Economics and Statistics",),
    ),
    Source(
        "JEEA",
        "Journal of the European Economic Association",
        "S165087003",
        "jeea",
        publisher="Oxford University Press",
        publisher_domains=("academic.oup.com",),
    ),
    Source(
        "EJ",
        "The Economic Journal",
        "S45992627",
        "ej",
        publisher="Oxford University Press",
        publisher_domains=("academic.oup.com",),
        title_aliases=("Economic Journal",),
    ),
]

DEFAULT_REVIEW_PATTERNS = [
    r"\bbook review\b",
    r"^\s*review essay\b",
    r"^\s*review of\b",
    r"\bedited by\b",
    r"\bPp\.\b",
    r"\.\s*By\s+[A-Z]",
]

DEFAULT_ABSTRACT_EXCLUDE_PATTERNS = [
    r"behavioral risk factor surveillance",
    r"developmental surveillance",
    r"surveillance department",
    r"post-market surveillance",
    r"budget surveillance",
    r"import surveillance",
]

THREAD_STATE = threading.local()
REQUEST_LOCK = threading.Lock()
ROBOTS_LOCK = threading.Lock()
LAST_REQUEST_AT: dict[str, float] = {}
ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def build_session() -> requests.Session:
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def worker_session() -> requests.Session:
    session = getattr(THREAD_STATE, "session", None)
    if session is None:
        session = build_session()
        THREAD_STATE.session = session
    return session


def api_get_json(
    session: requests.Session,
    url: str,
    config: dict,
    *,
    params: dict | None = None,
    timeout: int = 60,
) -> dict:
    response, note = polite_get(
        session,
        url,
        config,
        params=params,
        timeout=timeout,
        allow_redirects=True,
        purpose="api",
    )
    if response is None:
        raise requests.RequestException(note or f"failed to fetch {url}")
    response.raise_for_status()
    return response.json()


def normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    return doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/").strip()


def sanitize_filename_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value).strip("_").lower()
    return slug or "source"


def reconstruct_abstract(abstract_index: dict | None) -> str:
    if not abstract_index:
        return ""
    max_pos = max(position for positions in abstract_index.values() for position in positions)
    words = [""] * (max_pos + 1)
    for word, positions in abstract_index.items():
        for position in positions:
            words[position] = word
    return " ".join(words)


def dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def compile_patterns(values: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(value, re.IGNORECASE) for value in values]


def compile_keyword_rules(keywords: list[str]) -> dict[str, re.Pattern[str]]:
    rules: dict[str, re.Pattern[str]] = {}
    for keyword in keywords:
        escaped = re.escape(keyword.strip())
        rules[keyword] = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
    return rules


def first_author_surname(item: dict) -> str:
    authorships = item.get("authorships") or []
    if not authorships:
        return "source"
    display_name = ((authorships[0].get("author") or {}).get("display_name") or "").strip()
    if not display_name:
        return "source"
    return sanitize_filename_component(display_name.split()[-1])


def authors_string(item: dict) -> str:
    authors = []
    for authorship in item.get("authorships") or []:
        name = ((authorship.get("author") or {}).get("display_name") or "").strip()
        if name:
            authors.append(name)
    return "; ".join(authors)


def keyword_fields(item: dict) -> dict[str, str]:
    keyword_text = " ".join(
        keyword.get("display_name", "")
        for keyword in (item.get("keywords") or [])
        if isinstance(keyword, dict)
    )
    concept_text = " ".join(
        concept.get("display_name", "")
        for concept in (item.get("concepts") or [])
        if isinstance(concept, dict)
    )
    return {
        "title": (item.get("display_name") or item.get("title") or "").strip(),
        "abstract": item.get("__plain_abstract") or reconstruct_abstract(item.get("abstract_inverted_index")),
        "keywords": keyword_text,
        "concepts": concept_text,
    }


def source_titles(source: Source) -> tuple[str, ...]:
    extra = tuple(alias for alias in source.title_aliases if alias)
    return (source.display_name, *extra)


def source_matches_title(source: Source, title: str) -> bool:
    normalized = normalize_title(title)
    return normalized in {normalize_title(value) for value in source_titles(source)}


def load_pending_sources(path: Path) -> list[Source]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    sources: list[Source] = []
    for row in rows:
        display_name = str(row.get("display_name") or "").strip()
        filename_slug = str(row.get("filename_slug") or "").strip()
        code = str(row.get("code") or "").strip()
        if not display_name or not filename_slug or not code:
            continue
        publisher_domains = tuple(
            value.strip()
            for value in str(row.get("publisher_domains") or "").split(";")
            if value.strip()
        )
        title_aliases = tuple(
            value.strip()
            for value in str(row.get("title_aliases") or "").split(";")
            if value.strip()
        )
        sources.append(
            Source(
                code,
                display_name,
                str(row.get("openalex_source_id") or "").strip(),
                filename_slug,
                str(row.get("publisher") or "").strip(),
                publisher_domains,
                title_aliases,
            )
        )
    return sources


def merge_source_lists(primary: list[Source], extra: list[Source]) -> list[Source]:
    merged: list[Source] = []
    seen: set[tuple[str, str]] = set()
    for source in primary + extra:
        key = (source.filename_slug.lower(), normalize_title(source.display_name))
        if key in seen:
            continue
        seen.add(key)
        merged.append(source)
    return merged


def merge_sets(existing_value: object, new_values: Iterable[str]) -> set[str]:
    result = set(existing_value) if isinstance(existing_value, (set, list, tuple)) else set()
    result.update(value for value in new_values if value)
    return result


def choose_first(mapping: dict, *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value:
            return str(value).strip()
    return ""


def split_authors(raw_value: str) -> list[str]:
    parts = re.split(r"\s*[;,]\s*|\s+and\s+", raw_value.strip())
    return [part for part in parts if part]


def parse_crossref_abstract(raw_abstract: str | None) -> str:
    if not raw_abstract:
        return ""
    text = re.sub(r"</?[^>]+>", " ", raw_abstract)
    return re.sub(r"\s+", " ", text).strip()


def page_range(page_value: str | None) -> tuple[str, str]:
    if not page_value:
        return "", ""
    cleaned = page_value.replace(" ", "")
    if "-" not in cleaned:
        return cleaned, ""
    first, last = cleaned.split("-", 1)
    return first, last


def extract_date(item: dict) -> str:
    for key in ("published-print", "published-online", "issued", "created"):
        value = item.get(key) or {}
        parts = (value.get("date-parts") or [[]])[0]
        if parts:
            return "-".join(str(part) for part in parts)
    return ""


def maybe_wait_for_host(host: str, min_interval: float, jitter: float) -> None:
    with REQUEST_LOCK:
        now = time.time()
        next_allowed = LAST_REQUEST_AT.get(host, 0.0) + min_interval
        sleep_seconds = max(0.0, next_allowed - now)
        if sleep_seconds:
            time.sleep(sleep_seconds)
        LAST_REQUEST_AT[host] = time.time() + random.uniform(0.0, jitter)


def robots_allows(url: str, user_agent: str) -> bool:
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    with ROBOTS_LOCK:
        parser = ROBOTS_CACHE.get(robots_url)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(robots_url)
            try:
                parser.read()
            except Exception:
                parser = None
            ROBOTS_CACHE[robots_url] = parser
    if parser is None:
        return True
    try:
        return parser.can_fetch(user_agent, url)
    except Exception:
        return True


def polite_get(
    session: requests.Session,
    url: str,
    config: dict,
    *,
    params: dict | None = None,
    timeout: int = 60,
    allow_redirects: bool = True,
    purpose: str = "html",
) -> tuple[requests.Response | None, str | None]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    min_interval = config["api_request_delay_seconds"] if purpose == "api" else config["html_request_delay_seconds"]
    maybe_wait_for_host(host, min_interval, config["request_jitter_seconds"])
    if purpose == "html" and config["respect_robots_txt"] and not robots_allows(url, USER_AGENT):
        return None, f"{url}: blocked by robots.txt"
    try:
        response = session.get(url, params=params, timeout=timeout, allow_redirects=allow_redirects)
    except requests.RequestException as exc:
        return None, f"{url}: {exc.__class__.__name__}"
    if response.status_code in {403, 429}:
        retry_after = response.headers.get("Retry-After")
        sleep_seconds = config["anti_bot_backoff_seconds"]
        if retry_after and retry_after.isdigit():
            sleep_seconds = max(sleep_seconds, float(retry_after))
        time.sleep(sleep_seconds)
    return response, None


def load_config(config_path: Path | None, overrides: dict | None = None) -> dict:
    raw: dict
    if config_path is None:
        raw = {}
    else:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    if overrides:
        raw = {**raw, **{key: value for key, value in overrides.items() if value is not None}}

    keywords = [value.strip() for value in raw.get("keywords", []) if value.strip()]
    if not keywords:
        raise ValueError("Config must define at least one keyword.")

    output_dir = Path(raw["output_dir"])
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir

    pending_sources_path = Path(raw.get("pending_sources_path", PENDING_SOURCES_PATH))
    if not pending_sources_path.is_absolute():
        pending_sources_path = ROOT / pending_sources_path
    include_pending_sources = raw.get("include_pending_sources", True)

    journals = raw.get("journals")
    if journals:
        sources = [
            Source(
                journal["code"],
                journal["display_name"],
                journal["openalex_source_id"],
                journal["filename_slug"],
                journal.get("publisher", ""),
                tuple(journal.get("publisher_domains", [])),
                tuple(journal.get("title_aliases", [])),
            )
            for journal in journals
        ]
    else:
        sources = DEFAULT_SOURCES
        if include_pending_sources:
            sources = merge_source_lists(sources, load_pending_sources(pending_sources_path))

    review_patterns = compile_patterns(
        raw.get("review_title_patterns", DEFAULT_REVIEW_PATTERNS)
    )
    abstract_exclude_patterns = compile_patterns(
        raw.get("abstract_exclude_patterns", DEFAULT_ABSTRACT_EXCLUDE_PATTERNS)
    )

    config = {
        "prefix": raw["prefix"],
        "output_dir": output_dir,
        "keywords": keywords,
        "search_queries": raw.get("search_queries", keywords),
        "discovery_providers": raw.get("discovery_providers", ["openalex", "crossref"]),
        "openalex_discovery_strategies": raw.get(
            "openalex_discovery_strategies",
            raw.get("discovery_strategies", ["search", "title_search"]),
        ),
        "match_fields": raw.get("match_fields", ["title", "abstract"]),
        "match_mode": raw.get("match_mode", "any"),
        "year_cutoff": raw.get("year_cutoff"),
        "download_pdfs": raw.get("download_pdfs", True),
        "download_workers": raw.get("download_workers", 8),
        "write_candidates_jsonl": raw.get("write_candidates_jsonl", True),
        "write_summary_json": raw.get("write_summary_json", True),
        "dry_run": raw.get("dry_run", False),
        "scholar_csv_paths": raw.get("scholar_csv_paths", []),
        "respect_robots_txt": raw.get("respect_robots_txt", True),
        "api_request_delay_seconds": raw.get("api_request_delay_seconds", 0.2),
        "html_request_delay_seconds": raw.get("html_request_delay_seconds", 1.0),
        "request_jitter_seconds": raw.get("request_jitter_seconds", 0.2),
        "anti_bot_backoff_seconds": raw.get("anti_bot_backoff_seconds", 20.0),
        "include_pending_sources": include_pending_sources,
        "pending_sources_path": str(pending_sources_path),
        "sources": sources,
        "review_patterns": review_patterns,
        "abstract_exclude_patterns": abstract_exclude_patterns,
    }
    config["scholar_csv_paths"] = [
        str((ROOT / path) if not Path(path).is_absolute() else Path(path))
        for path in config["scholar_csv_paths"]
    ]
    if config["match_mode"] not in {"any", "all"}:
        raise ValueError("match_mode must be 'any' or 'all'.")
    for provider in config["discovery_providers"]:
        if provider not in {"openalex", "crossref", "scholar_csv"}:
            raise ValueError("discovery_providers entries must be openalex, crossref, or scholar_csv.")
    return config


def evaluate_match(item: dict, config: dict, keyword_rules: dict[str, re.Pattern[str]]) -> tuple[set[str], set[str]]:
    fields = keyword_fields(item)
    title = fields["title"]
    if not title:
        return set(), set()
    if any(pattern.search(title) for pattern in config["review_patterns"]):
        return set(), set()

    matched_terms: set[str] = set()
    matched_fields: set[str] = set()
    for field_name in config["match_fields"]:
        text = fields.get(field_name, "")
        if not text:
            continue
        for keyword, pattern in keyword_rules.items():
            if pattern.search(text):
                matched_terms.add(keyword)
                matched_fields.add(field_name)

    if matched_fields == {"abstract"} and any(
        pattern.search(fields["abstract"]) for pattern in config["abstract_exclude_patterns"]
    ):
        return set(), set()

    if config["match_mode"] == "all" and matched_terms != set(config["keywords"]):
        return set(), set()

    return matched_terms, matched_fields


def build_filter(source: Source, strategy: str, query: str, year_cutoff: int | None) -> str:
    filters = [
        f"primary_location.source.id:{source.openalex_source_id}",
        "type:article",
        "is_paratext:false",
    ]
    if year_cutoff is not None:
        filters.insert(1, f"from_publication_date:{year_cutoff}-01-01")
    if strategy == "title_search":
        filters.insert(0, f"title.search:{query}")
    return ",".join(filters)


OPENALEX_LOOKUP_CACHE: dict[str, dict | None] = {}


def openalex_lookup_by_doi(session: requests.Session, doi: str, config: dict) -> dict | None:
    normalized = normalize_doi(doi)
    if not normalized:
        return None
    if normalized in OPENALEX_LOOKUP_CACHE:
        return OPENALEX_LOOKUP_CACHE[normalized]
    payload = api_get_json(
        session,
        "https://api.openalex.org/works",
        config,
        params={"filter": f"doi:{normalized}", "per-page": 1},
    )
    result = (payload.get("results") or [None])[0]
    OPENALEX_LOOKUP_CACHE[normalized] = result
    return result


def record_from_crossref_item(item: dict, source: Source) -> dict:
    doi = normalize_doi(item.get("DOI"))
    title = (item.get("title") or [""])[0]
    first_page, last_page = page_range(item.get("page"))
    authorships = []
    for author in item.get("author") or []:
        display_name = " ".join(part for part in [author.get("given"), author.get("family")] if part).strip()
        if display_name:
            authorships.append({"author": {"display_name": display_name}})
    publication_date = extract_date(item)
    publication_year = None
    if publication_date:
        try:
            publication_year = int(publication_date.split("-", 1)[0])
        except ValueError:
            publication_year = None
    return {
        "id": f"crossref:{doi or item.get('URL') or title}",
        "doi": f"https://doi.org/{doi}" if doi else "",
        "title": title,
        "display_name": title,
        "publication_year": publication_year,
        "publication_date": publication_date,
        "primary_location": {"landing_page_url": item.get("URL") or (f"https://doi.org/{doi}" if doi else "")},
        "best_oa_location": {"landing_page_url": item.get("URL") or (f"https://doi.org/{doi}" if doi else "")},
        "open_access": {"is_oa": False, "oa_status": ""},
        "authorships": authorships,
        "biblio": {
            "volume": item.get("volume") or "",
            "issue": item.get("issue") or "",
            "first_page": first_page,
            "last_page": last_page,
        },
        "keywords": [],
        "concepts": [],
        "locations": [],
        "__plain_abstract": parse_crossref_abstract(item.get("abstract")),
        "__source_code": source.code,
        "__source_slug": source.filename_slug,
        "__source_display_name": source.display_name,
    }


def fetch_crossref_candidates_for_query(
    session: requests.Session,
    source: Source,
    query: str,
    config: dict,
) -> list[dict]:
    cursor = "*"
    collected: list[dict] = []
    while True:
        filters = ["type:journal-article"]
        if config["year_cutoff"] is not None:
            filters.append(f"from-pub-date:{config['year_cutoff']}-01-01")
        payload = api_get_json(
            session,
            "https://api.crossref.org/works",
            config,
            params={
                "query.bibliographic": query,
                "query.container-title": source.display_name,
                "rows": 100,
                "cursor": cursor,
                "mailto": "codex@example.com",
                "filter": ",".join(filters),
            },
        )
        message = payload.get("message") or {}
        items = message.get("items") or []
        if not items:
            break
        for item in items:
            container_titles = item.get("container-title") or []
            if not any(source_matches_title(source, value) for value in container_titles):
                continue
            record = record_from_crossref_item(item, source)
            doi = normalize_doi(record.get("doi"))
            if doi:
                try:
                    enriched = openalex_lookup_by_doi(session, doi, config)
                except requests.RequestException:
                    enriched = None
                if enriched:
                    record = enriched
                    record["__source_code"] = source.code
                    record["__source_slug"] = source.filename_slug
                    record["__source_display_name"] = source.display_name
            collected.append(record)
        next_cursor = message.get("next-cursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(config["api_request_delay_seconds"])
    return collected


def record_from_scholar_row(row: dict[str, str], source: Source) -> dict:
    title = choose_first(row, "Title", "title")
    doi = normalize_doi(choose_first(row, "DOI", "doi"))
    url = choose_first(row, "URL", "url", "Link", "link")
    year_raw = choose_first(row, "Year", "year")
    try:
        year = int(year_raw)
    except ValueError:
        year = None
    abstract = choose_first(row, "Abstract", "abstract", "Summary", "summary")
    authors = split_authors(choose_first(row, "Authors", "authors", "Author", "author"))
    return {
        "id": f"scholar:{doi or url or title}",
        "doi": f"https://doi.org/{doi}" if doi else "",
        "title": title,
        "display_name": title,
        "publication_year": year,
        "publication_date": str(year) if year else "",
        "primary_location": {"landing_page_url": url or (f"https://doi.org/{doi}" if doi else "")},
        "best_oa_location": {"landing_page_url": url or (f"https://doi.org/{doi}" if doi else "")},
        "open_access": {"is_oa": False, "oa_status": ""},
        "authorships": [{"author": {"display_name": value}} for value in authors],
        "biblio": {"volume": "", "issue": "", "first_page": "", "last_page": ""},
        "keywords": [],
        "concepts": [],
        "locations": [],
        "__plain_abstract": abstract,
        "__source_code": source.code,
        "__source_slug": source.filename_slug,
        "__source_display_name": source.display_name,
    }


def fetch_scholar_import_candidates(
    session: requests.Session,
    source: Source,
    config: dict,
) -> list[dict]:
    collected: list[dict] = []
    for csv_path in config["scholar_csv_paths"]:
        path = Path(csv_path)
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                source_value = choose_first(row, "Publication", "publication", "Source", "source", "Journal", "journal", "Venue", "venue")
                if not source_value or not source_matches_title(source, source_value):
                    continue
                record = record_from_scholar_row(row, source)
                doi = normalize_doi(record.get("doi"))
                if doi:
                    try:
                        enriched = openalex_lookup_by_doi(session, doi, config)
                    except requests.RequestException:
                        enriched = None
                    if enriched:
                        record = enriched
                        record["__source_code"] = source.code
                        record["__source_slug"] = source.filename_slug
                        record["__source_display_name"] = source.display_name
                collected.append(record)
    return collected


def store_candidate(
    candidates: dict[str, dict],
    item: dict,
    source: Source,
    matched_terms: set[str],
    matched_fields: set[str],
    query: str,
    strategy: str,
    provider: str,
) -> None:
    key = normalize_doi(item.get("doi")) or item["id"]
    existing = candidates.get(key)
    if existing is None:
        item["__source_code"] = source.code
        item["__source_slug"] = source.filename_slug
        item["__source_display_name"] = source.display_name
        item["__publisher"] = source.publisher
        item["__matched_terms"] = set(matched_terms)
        item["__matched_fields"] = set(matched_fields)
        item["__search_queries"] = {query}
        item["__discovery_strategies"] = {strategy}
        item["__metadata_sources"] = {provider}
        candidates[key] = item
        return

    existing["__matched_terms"] = merge_sets(existing.get("__matched_terms"), matched_terms)
    existing["__matched_fields"] = merge_sets(existing.get("__matched_fields"), matched_fields)
    existing["__search_queries"] = merge_sets(existing.get("__search_queries"), [query])
    existing["__discovery_strategies"] = merge_sets(existing.get("__discovery_strategies"), [strategy])
    existing["__metadata_sources"] = merge_sets(existing.get("__metadata_sources"), [provider])


def fetch_candidates(config: dict) -> list[dict]:
    session = build_session()
    keyword_rules = compile_keyword_rules(config["keywords"])
    candidates: dict[str, dict] = {}

    for source in config["sources"]:
        print(f"[discover] {source.display_name}")

        if "openalex" in config["discovery_providers"]:
            if not source.openalex_source_id:
                print("  - openalex skipped: pending source id")
            else:
                for query in config["search_queries"]:
                    for strategy in config["openalex_discovery_strategies"]:
                        page = 1
                        seen_this_query = 0
                        while True:
                            params = {
                                "filter": build_filter(source, strategy, query, config["year_cutoff"]),
                                "per-page": 200,
                                "page": page,
                            }
                            if strategy == "search":
                                params["search"] = query
                            payload = api_get_json(session, "https://api.openalex.org/works", config, params=params)
                            results = payload.get("results") or []
                            if not results:
                                break

                            for item in results:
                                matched_terms, matched_fields = evaluate_match(item, config, keyword_rules)
                                if not matched_terms:
                                    continue
                                store_candidate(candidates, item, source, matched_terms, matched_fields, query, strategy, "openalex")
                                seen_this_query += 1

                            total = (payload.get("meta") or {}).get("count", 0)
                            if page * 200 >= total:
                                break
                            page += 1
                            time.sleep(config["api_request_delay_seconds"])

                        print(f"  - {query} [openalex:{strategy}]: {seen_this_query} candidate hits")
                        time.sleep(config["api_request_delay_seconds"])

        if "crossref" in config["discovery_providers"]:
            for query in config["search_queries"]:
                seen_this_query = 0
                for item in fetch_crossref_candidates_for_query(session, source, query, config):
                    matched_terms, matched_fields = evaluate_match(item, config, keyword_rules)
                    if not matched_terms:
                        continue
                    store_candidate(candidates, item, source, matched_terms, matched_fields, query, "bibliographic", "crossref")
                    seen_this_query += 1
                print(f"  - {query} [crossref]: {seen_this_query} candidate hits")
                time.sleep(config["api_request_delay_seconds"])

        if "scholar_csv" in config["discovery_providers"] and config["scholar_csv_paths"]:
            seen_this_query = 0
            for item in fetch_scholar_import_candidates(session, source, config):
                matched_terms, matched_fields = evaluate_match(item, config, keyword_rules)
                if not matched_terms:
                    continue
                store_candidate(
                    candidates,
                    item,
                    source,
                    matched_terms,
                    matched_fields,
                    "__scholar_import__",
                    "csv_import",
                    "scholar_csv",
                )
                seen_this_query += 1
            print(f"  - scholar_csv [import]: {seen_this_query} candidate hits")

    records = list(candidates.values())
    records.sort(
        key=lambda item: (
            item.get("__source_slug", ""),
            item.get("publication_year") or 0,
            item.get("display_name") or "",
        )
    )
    print(f"[discover] total unique candidates: {len(records)}")
    return records


def maybe_pdf_response(response: requests.Response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    if "application/pdf" in content_type:
        return True
    return response.content[:5] == b"%PDF-"


def extract_html_pdf_candidates(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    for attr_name in ("citation_pdf_url", "wkhealth_pdf_url"):
        tag = soup.find("meta", attrs={"name": attr_name})
        if tag and tag.get("content"):
            urls.append(urljoin(base_url, tag["content"]))

    for tag in soup.find_all("a", href=True):
        href = urljoin(base_url, tag["href"])
        link_text = " ".join(tag.get_text(" ", strip=True).split()).lower()
        if href.lower().endswith(".pdf") or ".pdf?" in href.lower():
            urls.append(href)
        elif "pdf" in link_text and href.startswith("http"):
            urls.append(href)

    return dedupe(urls)


def guessed_pdf_urls(landing_url: str) -> list[str]:
    urls: list[str] = []
    if "jstor.org/stable/" in landing_url:
        stable_id = landing_url.split("jstor.org/stable/", 1)[1].split("?", 1)[0].strip("/")
        if stable_id:
            urls.append(f"https://www.jstor.org/stable/pdf/{stable_id}.pdf")

    pii_match = re.search(r"/pii/([A-Z0-9]+)", landing_url)
    if pii_match and "sciencedirect.com" in landing_url:
        pii = pii_match.group(1)
        urls.extend(
            [
                f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true",
                f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft",
            ]
        )

    doi_match = re.search(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", landing_url, re.IGNORECASE)
    if doi_match:
        doi = doi_match.group(1)
        if "journals.uchicago.edu" in landing_url:
            urls.append(f"https://www.journals.uchicago.edu/doi/pdf/{doi}")
        if "onlinelibrary.wiley.com" in landing_url:
            urls.extend(
                [
                    f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}",
                    f"https://onlinelibrary.wiley.com/doi/pdf/{doi}",
                ]
            )

    return dedupe(urls)


def crossref_fulltext_links(session: requests.Session, doi: str, config: dict) -> list[str]:
    try:
        payload = api_get_json(
            session,
            f"https://api.crossref.org/works/{quote(doi, safe='')}",
            config,
        )
    except requests.RequestException:
        return []
    links = []
    for link in (payload.get("message") or {}).get("link") or []:
        url = link.get("URL")
        content_type = (link.get("content-type") or "").lower()
        if url and "pdf" in content_type:
            links.append(url)
    return dedupe(links)


def gather_candidate_urls(session: requests.Session, item: dict, config: dict) -> list[str]:
    urls: list[str] = []
    oa = item.get("best_oa_location") or {}
    primary = item.get("primary_location") or {}
    open_access = item.get("open_access") or {}
    locations = item.get("locations") or []
    doi = normalize_doi(item.get("doi"))

    for candidate in (oa, primary):
        if candidate.get("pdf_url"):
            urls.append(candidate["pdf_url"])
        if candidate.get("landing_page_url"):
            urls.append(candidate["landing_page_url"])

    if open_access.get("oa_url"):
        urls.append(open_access["oa_url"])

    for location in locations:
        if location.get("pdf_url"):
            urls.append(location["pdf_url"])
        if location.get("landing_page_url"):
            urls.append(location["landing_page_url"])

    if doi:
        urls.append(f"https://doi.org/{doi}")
        urls.extend(crossref_fulltext_links(session, doi, config))

    expanded: list[str] = []
    for url in dedupe(urls):
        expanded.append(url)
        expanded.extend(guessed_pdf_urls(url))
    return dedupe(expanded)


def unique_path(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path
    stem = base_path.stem
    suffix = base_path.suffix
    counter = 2
    while True:
        candidate = base_path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def download_pdf(session: requests.Session, item: dict, output_dir: Path, config: dict) -> tuple[Path | None, str]:
    candidate_urls = gather_candidate_urls(session, item, config)
    if not candidate_urls:
        return None, "no candidate URLs"

    last_note = "no PDF located"
    for url in candidate_urls:
        response, note = polite_get(
            session,
            url,
            config,
            timeout=45,
            allow_redirects=True,
            purpose="html",
        )
        if response is None:
            last_note = note or f"{url}: request failed"
            continue

        final_url = response.url
        if response.status_code >= 400:
            last_note = f"{final_url}: HTTP {response.status_code}"
            continue

        if maybe_pdf_response(response):
            year = item.get("publication_year") or "undated"
            filename = f"{first_author_surname(item)}_{year}_{item['__source_slug']}.pdf"
            path = unique_path(output_dir / filename)
            path.write_bytes(response.content)
            return path, f"downloaded from {final_url}"

        content_type = (response.headers.get("content-type") or "").lower()
        if "html" not in content_type:
            last_note = f"{final_url}: non-PDF content-type {content_type or 'unspecified'}"
            continue

        embedded_urls = extract_html_pdf_candidates(response.text, final_url) + guessed_pdf_urls(final_url)
        for pdf_url in dedupe(embedded_urls):
            pdf_response, note = polite_get(
                session,
                pdf_url,
                config,
                timeout=45,
                allow_redirects=True,
                purpose="html",
            )
            if pdf_response is None:
                last_note = note or f"{pdf_url}: request failed"
                continue
            if pdf_response.status_code >= 400:
                last_note = f"{pdf_response.url}: HTTP {pdf_response.status_code}"
                continue
            if not maybe_pdf_response(pdf_response):
                last_note = f"{pdf_response.url}: HTML page without PDF payload"
                continue

            year = item.get("publication_year") or "undated"
            filename = f"{first_author_surname(item)}_{year}_{item['__source_slug']}.pdf"
            path = unique_path(output_dir / filename)
            path.write_bytes(pdf_response.content)
            return path, f"downloaded from {pdf_response.url}"

        last_note = f"{final_url}: no PDF link found in landing page"

    return None, last_note


def landing_url(item: dict) -> str:
    for candidate in (item.get("best_oa_location") or {}, item.get("primary_location") or {}):
        if candidate.get("landing_page_url"):
            return candidate["landing_page_url"]
    doi = normalize_doi(item.get("doi"))
    return f"https://doi.org/{doi}" if doi else ""


def manifest_row(item: dict, download_path: Path | None, note: str) -> dict[str, str]:
    doi = normalize_doi(item.get("doi"))
    biblio = item.get("biblio") or {}
    open_access = item.get("open_access") or {}
    return {
        "downloaded": "yes" if download_path else "no",
        "local_filename": download_path.name if download_path else "",
        "journal": item.get("__source_display_name", ""),
        "journal_code": item.get("__source_slug", ""),
        "publisher": item.get("__publisher", ""),
        "title": item.get("display_name") or "",
        "authors": authors_string(item),
        "first_author": first_author_surname(item),
        "year": str(item.get("publication_year") or ""),
        "publication_date": item.get("publication_date") or "",
        "doi": doi,
        "doi_url": f"https://doi.org/{doi}" if doi else "",
        "openalex_id": item.get("id") or "",
        "volume": biblio.get("volume") or "",
        "issue": biblio.get("issue") or "",
        "first_page": biblio.get("first_page") or "",
        "last_page": biblio.get("last_page") or "",
        "landing_page_url": landing_url(item),
        "is_oa": str(open_access.get("is_oa") if open_access else ""),
        "oa_status": open_access.get("oa_status") or "",
        "matched_terms": "; ".join(sorted(item.get("__matched_terms") or [])),
        "matched_fields": "; ".join(sorted(item.get("__matched_fields") or [])),
        "search_queries": "; ".join(sorted(item.get("__search_queries") or [])),
        "discovery_strategies": "; ".join(sorted(item.get("__discovery_strategies") or [])),
        "metadata_sources": "; ".join(sorted(item.get("__metadata_sources") or [])),
        "download_note": note,
    }


def download_worker(index: int, item: dict, output_dir: Path, config: dict) -> tuple[int, dict, Path | None, str]:
    path, note = download_pdf(worker_session(), item, output_dir, config)
    return index, item, path, note


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_candidates_jsonl(path: Path, candidates: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in candidates:
            serializable = dict(item)
            serializable["__matched_terms"] = sorted(serializable.get("__matched_terms", []))
            serializable["__matched_fields"] = sorted(serializable.get("__matched_fields", []))
            serializable["__search_queries"] = sorted(serializable.get("__search_queries", []))
            serializable["__discovery_strategies"] = sorted(serializable.get("__discovery_strategies", []))
            serializable["__metadata_sources"] = sorted(serializable.get("__metadata_sources", []))
            handle.write(json.dumps(serializable, ensure_ascii=False) + "\n")


def write_summary_json(path: Path, config: dict, total: int, downloaded_rows: int, missing_rows: int) -> None:
    summary = {
        "prefix": config["prefix"],
        "keywords": config["keywords"],
        "search_queries": config["search_queries"],
        "discovery_providers": config["discovery_providers"],
        "openalex_discovery_strategies": config["openalex_discovery_strategies"],
        "match_fields": config["match_fields"],
        "match_mode": config["match_mode"],
        "year_cutoff": config["year_cutoff"],
        "download_pdfs": config["download_pdfs"],
        "respect_robots_txt": config["respect_robots_txt"],
        "total_candidates": total,
        "downloaded_rows": downloaded_rows,
        "metadata_only_rows": missing_rows,
        "sources": [source.__dict__ for source in config["sources"]],
    }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def run_batch(config: dict) -> None:
    output_dir = config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = config["prefix"]
    candidates_path = output_dir / f"{prefix}_candidates.jsonl"
    manifest_path = output_dir / f"{prefix}_download_manifest.csv"
    missing_path = output_dir / f"{prefix}_undownloadable_metadata.csv"
    summary_path = output_dir / f"{prefix}_summary.json"

    candidates = fetch_candidates(config)
    if config["write_candidates_jsonl"]:
        write_candidates_jsonl(candidates_path, candidates)

    if config["dry_run"] or not config["download_pdfs"]:
        rows = [manifest_row(item, None, "download skipped by config") for item in candidates]
        write_csv(manifest_path, rows)
        write_csv(missing_path, rows)
        if config["write_summary_json"]:
            write_summary_json(summary_path, config, len(candidates), 0, len(candidates))
        print("[summary] dry run complete")
        print(f"[summary] manifest: {manifest_path}")
        print(f"[summary] candidates: {candidates_path}")
        return

    indexed_rows: dict[int, dict[str, str]] = {}
    download_counts: defaultdict[str, int] = defaultdict(int)
    missing_counts: defaultdict[str, int] = defaultdict(int)

    total = len(candidates)
    with ThreadPoolExecutor(max_workers=config["download_workers"]) as executor:
        future_map = {
            executor.submit(download_worker, index, item, output_dir, config): (index, item)
            for index, item in enumerate(candidates, start=1)
        }
        for future in as_completed(future_map):
            index, item, path, note = future.result()
            title = item.get("display_name") or ""
            journal = item.get("__source_display_name") or ""
            status = "saved" if path else "metadata only"
            print(f"[download] {index}/{total} | {journal} | {title[:120]} | {status}")
            row = manifest_row(item, path, note)
            indexed_rows[index] = row
            if path:
                download_counts[item["__source_slug"]] += 1
            else:
                missing_counts[item["__source_slug"]] += 1

    all_rows: list[dict[str, str]] = []
    missing_rows: list[dict[str, str]] = []
    for index in sorted(indexed_rows):
        row = indexed_rows[index]
        all_rows.append(row)
        if row["downloaded"] == "no":
            missing_rows.append(row)

    write_csv(manifest_path, all_rows)
    write_csv(missing_path, missing_rows)

    print("[summary] downloaded")
    for source in config["sources"]:
        count = download_counts[source.filename_slug]
        if count:
            print(f"  - {source.filename_slug}: {count}")

    print("[summary] metadata only")
    for source in config["sources"]:
        count = missing_counts[source.filename_slug]
        if count:
            print(f"  - {source.filename_slug}: {count}")

    if config["write_summary_json"]:
        write_summary_json(summary_path, config, len(candidates), len(all_rows) - len(missing_rows), len(missing_rows))

    print(f"[summary] total candidates: {len(candidates)}")
    print(f"[summary] candidates: {candidates_path}")
    print(f"[summary] manifest: {manifest_path}")
    print(f"[summary] undownloadable metadata: {missing_path}")
    print(f"[summary] summary json: {summary_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to a TOML config file.")
    parser.add_argument("--output-dir", help="Override output directory.")
    parser.add_argument("--prefix", help="Override output prefix.")
    parser.add_argument("--keywords", nargs="+", help="Override exact keywords to match.")
    parser.add_argument("--search-queries", nargs="+", help="Override broad discovery queries.")
    parser.add_argument("--year-cutoff", type=int, help="Optional publication year cutoff.")
    parser.add_argument("--dry-run", action="store_true", help="Skip PDF downloads and only export metadata.")
    parser.add_argument(
        "--scholar-csv",
        action="append",
        default=[],
        help="Optional local CSV exported from Google Scholar tools such as Publish or Perish.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.config and not (args.output_dir and args.prefix and args.keywords):
        raise SystemExit("Provide --config or at minimum --output-dir, --prefix, and --keywords.")
    overrides = {
        "output_dir": args.output_dir,
        "prefix": args.prefix,
        "keywords": args.keywords,
        "search_queries": args.search_queries,
        "year_cutoff": args.year_cutoff,
        "dry_run": True if args.dry_run else None,
        "scholar_csv_paths": args.scholar_csv or None,
    }
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path, overrides)
    run_batch(config)


if __name__ == "__main__":
    main()
