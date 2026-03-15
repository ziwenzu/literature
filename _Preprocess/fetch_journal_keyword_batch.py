#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
import threading
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path("/Users/ziwenzu/Library/CloudStorage/Dropbox")
USER_AGENT = "Mozilla/5.0 (compatible; Codex/1.0; +mailto:codex@example.com)"
REQUEST_HEADERS = {"User-Agent": USER_AGENT}
DOWNLOAD_WORKERS = 8


@dataclass(frozen=True)
class Source:
    code: str
    display_name: str
    openalex_source_id: str
    filename_slug: str


SOURCES = [
    Source("APSR", "American Political Science Review", "S176007004", "apsr"),
    Source("AJPS", "American Journal of Political Science", "S90314269", "ajps"),
    Source("JOP", "The Journal of Politics", "S95650557", "jop"),
    Source("AER", "American Economic Review", "S23254222", "aer"),
    Source("JPUBECO", "Journal of Public Economics", "S199447588", "jpubeco"),
    Source("BJPS", "British Journal of Political Science", "S95691132", "bjps"),
    Source("PSRM", "Political Science Research and Methods", "S2764571748", "psrm"),
    Source("CPS", "Comparative Political Studies", "S105556297", "cps"),
    Source("QJPS", "Quarterly Journal of Political Science", "S44648735", "qjps"),
    Source(
        "JEPS",
        "Journal of Experimental Political Science",
        "S4210184980",
        "jeps",
    ),
    Source("CQ", "The China Quarterly", "S12189451", "cq"),
    Source("JCC", "Journal of Contemporary China", "S102994345", "jcc"),
    Source("EJ", "The Economic Journal", "S45992627", "ej"),
    Source("JPE", "Journal of Political Economy", "S95323914", "jpe"),
    Source(
        "AEJAPPLIED",
        "American Economic Journal: Applied Economics",
        "S42893225",
        "aejapplied",
    ),
    Source(
        "AEJPOLICY",
        "American Economic Journal: Economic Policy",
        "S158011328",
        "aejpolicy",
    ),
    Source(
        "AEJMACRO",
        "American Economic Journal: Macroeconomics",
        "S170166683",
        "aejmacro",
    ),
    Source(
        "AEJMICRO",
        "American Economic Journal: Microeconomics",
        "S96919139",
        "aejmicro",
    ),
    Source(
        "AEJINSIGHTS",
        "American Economic Review Insights",
        "S4210174288",
        "aejinsights",
    ),
    Source(
        "JEEA",
        "Journal of the European Economic Association",
        "S165087003",
        "jeea",
    ),
    Source(
        "RESTAT",
        "The Review of Economics and Statistics",
        "S180061323",
        "restat",
    ),
]

REVIEW_TITLE_RULES = [
    re.compile(r"\bbook review\b", re.IGNORECASE),
    re.compile(r"^\s*review essay\b", re.IGNORECASE),
    re.compile(r"^\s*review of\b", re.IGNORECASE),
    re.compile(r"\bedited by\b", re.IGNORECASE),
    re.compile(r"\bPp\.\b", re.IGNORECASE),
    re.compile(r"\.\s*By\s+[A-Z]", re.IGNORECASE),
]

ABSTRACT_EXCLUDE_RULES = [
    re.compile(r"behavioral risk factor surveillance", re.IGNORECASE),
    re.compile(r"developmental surveillance", re.IGNORECASE),
    re.compile(r"surveillance department", re.IGNORECASE),
    re.compile(r"post-market surveillance", re.IGNORECASE),
    re.compile(r"budget surveillance", re.IGNORECASE),
    re.compile(r"import surveillance", re.IGNORECASE),
]


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


THREAD_STATE = threading.local()


def worker_session() -> requests.Session:
    session = getattr(THREAD_STATE, "session", None)
    if session is None:
        session = build_session()
        THREAD_STATE.session = session
    return session


def api_get_json(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    timeout: int = 60,
) -> dict:
    response = session.get(url, params=params, timeout=timeout)
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
    return slug or "unknown"


def first_author_surname(item: dict) -> str:
    authorships = item.get("authorships") or []
    if not authorships:
        return "unknown"
    display_name = ((authorships[0].get("author") or {}).get("display_name") or "").strip()
    if not display_name:
        return "unknown"
    surname = display_name.split()[-1]
    return sanitize_filename_component(surname)


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


def compile_keyword_rules(keywords: list[str]) -> dict[str, re.Pattern[str]]:
    rules: dict[str, re.Pattern[str]] = {}
    for keyword in keywords:
        escaped = re.escape(keyword.strip())
        pattern = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
        rules[keyword] = pattern
    return rules


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
        "abstract": reconstruct_abstract(item.get("abstract_inverted_index")),
        "keywords": keyword_text,
        "concepts": concept_text,
    }


def evaluate_match(item: dict, keyword_rules: dict[str, re.Pattern[str]]) -> tuple[set[str], set[str]]:
    fields = keyword_fields(item)
    title = fields["title"]
    if not title:
        return set(), set()
    if any(pattern.search(title) for pattern in REVIEW_TITLE_RULES):
        return set(), set()

    matched_terms: set[str] = set()
    matched_fields: set[str] = set()
    for field_name in ("title", "abstract"):
        text = fields[field_name]
        if not text:
            continue
        for keyword, pattern in keyword_rules.items():
            if pattern.search(text):
                matched_terms.add(keyword)
                matched_fields.add(field_name)

    if matched_fields == {"abstract"} and any(
        pattern.search(fields["abstract"]) for pattern in ABSTRACT_EXCLUDE_RULES
    ):
        return set(), set()

    return matched_terms, matched_fields


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


def crossref_fulltext_links(session: requests.Session, doi: str) -> list[str]:
    try:
        payload = api_get_json(session, f"https://api.crossref.org/works/{quote(doi, safe='')}")
    except requests.RequestException:
        return []
    links = []
    for link in (payload.get("message") or {}).get("link") or []:
        url = link.get("URL")
        content_type = (link.get("content-type") or "").lower()
        if url and "pdf" in content_type:
            links.append(url)
    return dedupe(links)


def gather_candidate_urls(session: requests.Session, item: dict) -> list[str]:
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
        urls.extend(crossref_fulltext_links(session, doi))

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


def download_pdf(session: requests.Session, item: dict, output_dir: Path) -> tuple[Path | None, str]:
    candidate_urls = gather_candidate_urls(session, item)
    if not candidate_urls:
        return None, "no candidate URLs"

    last_note = "no PDF located"
    for url in candidate_urls:
        try:
            response = session.get(url, timeout=45, allow_redirects=True)
        except requests.RequestException as exc:
            last_note = f"{url}: {exc.__class__.__name__}"
            continue

        final_url = response.url
        if response.status_code >= 400:
            last_note = f"{final_url}: HTTP {response.status_code}"
            continue

        if maybe_pdf_response(response):
            year = item.get("publication_year") or "unknown"
            filename = f"{first_author_surname(item)}_{year}_{item['__source_slug']}.pdf"
            path = unique_path(output_dir / filename)
            path.write_bytes(response.content)
            return path, f"downloaded from {final_url}"

        content_type = (response.headers.get("content-type") or "").lower()
        if "html" not in content_type:
            last_note = f"{final_url}: non-PDF content-type {content_type or 'unknown'}"
            continue

        embedded_urls = extract_html_pdf_candidates(response.text, final_url) + guessed_pdf_urls(final_url)
        for pdf_url in dedupe(embedded_urls):
            try:
                pdf_response = session.get(pdf_url, timeout=45, allow_redirects=True)
            except requests.RequestException as exc:
                last_note = f"{pdf_url}: {exc.__class__.__name__}"
                continue
            if pdf_response.status_code >= 400:
                last_note = f"{pdf_response.url}: HTTP {pdf_response.status_code}"
                continue
            if not maybe_pdf_response(pdf_response):
                last_note = f"{pdf_response.url}: HTML page without PDF payload"
                continue

            year = item.get("publication_year") or "unknown"
            filename = f"{first_author_surname(item)}_{year}_{item['__source_slug']}.pdf"
            path = unique_path(output_dir / filename)
            path.write_bytes(pdf_response.content)
            return path, f"downloaded from {pdf_response.url}"

        last_note = f"{final_url}: no PDF link found in landing page"

    return None, last_note


def authors_string(item: dict) -> str:
    authors = []
    for authorship in item.get("authorships") or []:
        name = ((authorship.get("author") or {}).get("display_name") or "").strip()
        if name:
            authors.append(name)
    return "; ".join(authors)


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
        "search_terms_triggered": "; ".join(sorted(item.get("__search_terms") or [])),
        "download_note": note,
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fetch_candidates(keywords: list[str], year_cutoff: int | None) -> list[dict]:
    session = build_session()
    keyword_rules = compile_keyword_rules(keywords)
    candidates: dict[str, dict] = {}

    for source in SOURCES:
        print(f"[discover] {source.display_name}")
        for keyword in keywords:
            filters = [
                f"primary_location.source.id:{source.openalex_source_id}",
                "type:article",
                "is_paratext:false",
            ]
            if year_cutoff is not None:
                filters.insert(1, f"from_publication_date:{year_cutoff}-01-01")
            filter_value = ",".join(filters)

            page = 1
            seen_this_query = 0
            while True:
                payload = api_get_json(
                    session,
                    "https://api.openalex.org/works",
                    params={
                        "search": keyword,
                        "filter": filter_value,
                        "per-page": 200,
                        "page": page,
                    },
                )
                results = payload.get("results") or []
                if not results:
                    break

                for item in results:
                    matched_terms, matched_fields = evaluate_match(item, keyword_rules)
                    if not matched_terms:
                        continue

                    key = normalize_doi(item.get("doi")) or item["id"]
                    existing = candidates.get(key)
                    if existing is None:
                        item["__source_code"] = source.code
                        item["__source_slug"] = source.filename_slug
                        item["__source_display_name"] = source.display_name
                        item["__matched_terms"] = set(matched_terms)
                        item["__matched_fields"] = set(matched_fields)
                        item["__search_terms"] = {keyword}
                        candidates[key] = item
                    else:
                        existing["__matched_terms"].update(matched_terms)
                        existing["__matched_fields"].update(matched_fields)
                        existing["__search_terms"].add(keyword)
                    seen_this_query += 1

                total = (payload.get("meta") or {}).get("count", 0)
                if page * 200 >= total:
                    break
                page += 1
                time.sleep(0.15)

            print(f"  - {keyword}: {seen_this_query} candidate hits")
            time.sleep(0.15)

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


def download_worker(index: int, total: int, item: dict, output_dir: Path) -> tuple[int, dict, Path | None, str]:
    path, note = download_pdf(worker_session(), item, output_dir)
    return index, item, path, note


def run_batch(output_dir: Path, prefix: str, keywords: list[str], year_cutoff: int | None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"{prefix}_download_manifest.csv"
    missing_path = output_dir / f"{prefix}_undownloadable_metadata.csv"

    candidates = fetch_candidates(keywords, year_cutoff)
    all_rows: list[dict[str, str]] = []
    missing_rows: list[dict[str, str]] = []
    download_counts: defaultdict[str, int] = defaultdict(int)
    missing_counts: defaultdict[str, int] = defaultdict(int)
    indexed_rows: dict[int, dict[str, str]] = {}

    total = len(candidates)
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        futures = [
            executor.submit(download_worker, index, total, item, output_dir)
            for index, item in enumerate(candidates, start=1)
        ]
        for future in as_completed(futures):
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

    for index in sorted(indexed_rows):
        row = indexed_rows[index]
        all_rows.append(row)
        if row["downloaded"] == "no":
            missing_rows.append(row)

    write_csv(manifest_path, all_rows)
    write_csv(missing_path, missing_rows)

    print("[summary] downloaded")
    for source in SOURCES:
        count = download_counts[source.filename_slug]
        if count:
            print(f"  - {source.filename_slug}: {count}")

    print("[summary] metadata only")
    for source in SOURCES:
        count = missing_counts[source.filename_slug]
        if count:
            print(f"  - {source.filename_slug}: {count}")

    print(f"[summary] total candidates: {len(candidates)}")
    print(f"[summary] manifest: {manifest_path}")
    print(f"[summary] undownloadable metadata: {missing_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--keywords", nargs="+", required=True)
    parser.add_argument("--year-cutoff", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    keywords = [keyword.strip() for keyword in args.keywords if keyword.strip()]
    run_batch(output_dir, args.prefix, keywords, args.year_cutoff)


if __name__ == "__main__":
    main()
