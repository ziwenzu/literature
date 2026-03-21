#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


REFERENCE_HEADERS = re.compile(
    r"(?im)^\s*(references|bibliography|works cited|literature cited)\s*$"
)
YEAR_RE = re.compile(r"\b(?:17|18|19|20)\d{2}[a-z]?\b")
APPENDIX_HINT_RE = re.compile(
    r"(?im)^\s*(appendix|online appendix|supplementary|supporting information|tables? |figures? )"
)
URL_RE = re.compile(r"https?://\S+")
WHITESPACE_RE = re.compile(r"\s+")
INLINE_REFERENCE_BREAK_PATTERNS = [
    re.compile(
        r'(?<=[.?!”"\)])\s+(?=[A-Z]{2,}(?:\s+[A-Z]{2,})*,\s*\d{4}[a-z]?\b)'
    ),
    re.compile(
        r'(?<=[.?!”"\)])\s+(?=[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ\'`’.\-]+,\s+[^.\n]{0,120}\b(?:17|18|19|20)\d{2}[a-z]?\b)'
    ),
    re.compile(
        r'(?<=[.?!”"\)])\s+(?=[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ\'`’.\-]+(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ\'`’.\-]+)*\s+(?:et al\.|and)\b[^\n]{0,80}\(\d{4}[a-z]?\))'
    ),
]
@dataclass
class PdfStatus:
    pdf_name: str
    pages: int
    detected_start_page: int | None
    detected_end_page: int | None
    method: str
    extracted_references: int
    note: str


def run_command(command: list[str]) -> str:
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"command failed: {' '.join(command)}")
    return proc.stdout


def pdf_page_count(pdf_path: Path) -> int:
    info = run_command(["pdfinfo", str(pdf_path)])
    match = re.search(r"^Pages:\s+(\d+)$", info, flags=re.MULTILINE)
    if not match:
        raise RuntimeError(f"unable to determine page count for {pdf_path}")
    return int(match.group(1))


def extract_page_text(pdf_path: Path, page: int) -> str:
    layout_text = run_command(
        [
            "pdftotext",
            "-layout",
            "-nopgbrk",
            "-f",
            str(page),
            "-l",
            str(page),
            str(pdf_path),
            "-",
        ]
    )
    reflowed = reflow_two_column_text(layout_text)
    if reflowed is not None:
        return reflowed
    return run_command(
        [
            "pdftotext",
            "-nopgbrk",
            "-f",
            str(page),
            "-l",
            str(page),
            str(pdf_path),
            "-",
        ]
    )


def normalize_space(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text.replace("\u00ad", "")).strip()


def strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def normalize_reference_for_compare(text: str) -> str:
    cleaned = URL_RE.sub(" ", text)
    cleaned = strip_accents(cleaned).lower()
    cleaned = re.sub(r"\bdoi\s*:?\s*", " ", cleaned)
    cleaned = re.sub(r"\bvols?\.\b|\bnos?\.\b|\bpp?\.\b", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    return normalize_space(cleaned)


def reflow_two_column_text(layout_text: str) -> str | None:
    lines = layout_text.splitlines()
    gap_midpoints: list[int] = []
    for line in lines:
        for match in re.finditer(r" {14,}", line):
            gap_midpoints.append((match.start() + match.end()) // 2)
    if len(gap_midpoints) < 20:
        return None

    split = int(statistics.median(gap_midpoints))
    if split < 55 or split > 120:
        return None

    stable_points = [point for point in gap_midpoints if abs(point - split) <= 12]
    if len(stable_points) / max(len(gap_midpoints), 1) < 0.45:
        return None

    left_lines: list[str] = []
    right_lines: list[str] = []
    for line in lines:
        if len(line) > split:
            left = line[:split].rstrip()
            right = line[split:].strip()
        else:
            left = line.rstrip()
            right = ""
        if left.strip():
            left_lines.append(left)
        if right.strip():
            right_lines.append(right)
    return "\n".join(left_lines + [""] + right_lines)


def skip_line(line: str) -> bool:
    stripped = normalize_space(line)
    if not stripped:
        return True
    lowered = stripped.lower()
    if lowered in {"references", "bibliography", "works cited", "literature cited"}:
        return True
    if re.fullmatch(r"\d+", stripped):
        return True
    if lowered.startswith("published online by"):
        return True
    if stripped.startswith("https://doi.org/") and "published online by" in lowered:
        return True
    if lowered.startswith("downloaded from "):
        return True
    if lowered.startswith("copyright ") or stripped.startswith("©"):
        return True
    if re.fullmatch(r"\[[A-Za-z]+\s+\d{4}\]", stripped):
        return True
    if "creativecommons.org/licenses" in lowered:
        return True
    if is_garbled_line(stripped):
        return True
    return False


def referenceish_line(line: str) -> bool:
    stripped = normalize_space(line)
    if len(stripped) < 20:
        return False
    if skip_line(stripped):
        return False
    year_match = YEAR_RE.search(stripped[:220])
    if not year_match:
        return False
    if re.match(r"^[,—-]", stripped):
        return True
    if re.match(r"^[A-Z]{2,}(?:\s+[A-Z]{2,})*,\s*\d{4}[a-z]?\b", stripped):
        return True
    if re.match(
        r"^[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ'`’.\-]+(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ'`’.\-]+)*\s+(?:et al\.|and)\b.*\(\d{4}[a-z]?\)",
        stripped,
    ):
        return True
    if re.match(r"^[A-ZÀ-ÖØ-Ý][^.;]{0,80}\(\d{4}[a-z]?\)", stripped):
        return True
    if re.match(r"^[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÿ'`’.\-]+,", stripped):
        prefix = stripped[: year_match.start()]
        if prefix.count(",") >= 2:
            return True
    return False


def is_garbled_line(line: str) -> bool:
    if len(line) < 16:
        return False
    letters = sum(char.isalpha() for char in line)
    weird = sum(
        not (char.isascii() and (char.isalnum() or char.isspace() or char in ".,;:!?()[]{}'\"/&%+-=–—"))
        for char in line
    )
    return weird >= 6 and letters / max(len(line), 1) < 0.45


def page_header_like(line: str) -> bool:
    stripped = normalize_space(line)
    lowered = stripped.lower()
    if not stripped:
        return False
    if lowered.startswith("vol. "):
        return True
    if re.search(r"\b(?:journal|review|quarterly|economic)\b.*\(\d{4}\)\s+\d+[–-]\d+", lowered):
        return True
    if re.search(r"\bno\.\s+\d", lowered) and re.search(r"\b\d{2,4}$", lowered):
        return True
    if re.search(r"\bpublished online by\b", lowered):
        return True
    return False


def page_reference_score(text: str) -> tuple[int, int]:
    nonempty_lines = 0
    ref_lines = 0
    for raw_line in text.splitlines():
        if not normalize_space(raw_line):
            continue
        nonempty_lines += 1
        if referenceish_line(raw_line):
            ref_lines += 1
    return ref_lines, nonempty_lines


def find_contiguous_blocks(pages: list[int]) -> list[list[int]]:
    if not pages:
        return []
    blocks: list[list[int]] = [[pages[0]]]
    for page in pages[1:]:
        if page == blocks[-1][-1] + 1:
            blocks[-1].append(page)
        else:
            blocks.append([page])
    return blocks


def detect_reference_pages(page_texts: dict[int, str]) -> tuple[list[int], str, str]:
    header_pages = [
        page for page, text in page_texts.items() if REFERENCE_HEADERS.search(text)
    ]
    scores = {page: page_reference_score(text) for page, text in page_texts.items()}
    strong_pages = [
        page
        for page, (ref_lines, nonempty_lines) in scores.items()
        if ref_lines >= 5 or (ref_lines >= 3 and ref_lines / max(nonempty_lines, 1) >= 0.11)
    ]

    if header_pages:
        start_page = header_pages[-1]
        selected: list[int] = []
        saw_references = False
        for page in range(start_page, max(page_texts) + 1):
            text = page_texts[page]
            ref_lines, nonempty_lines = scores[page]
            is_reference_page = (
                page == start_page
                or ref_lines >= 3
                or (ref_lines >= 2 and ref_lines / max(nonempty_lines, 1) >= 0.08)
            )
            if is_reference_page:
                selected.append(page)
                saw_references = True
                continue
            if saw_references and APPENDIX_HINT_RE.search(text):
                break
            if saw_references and ref_lines == 0:
                break
        if selected:
            return selected, "header", ""

    trailing_window_start = max(1, max(page_texts) - 24)
    candidate_pages = [page for page in strong_pages if page >= trailing_window_start]
    blocks = find_contiguous_blocks(candidate_pages)
    if blocks:
        best_block = max(
            blocks,
            key=lambda block: (
                sum(scores[page][0] for page in block),
                block[-1],
                len(block),
            ),
        )
        return best_block, "density", ""

    return [], "none", "no standard references section detected"


def trim_to_header_if_needed(text: str) -> str:
    match = list(REFERENCE_HEADERS.finditer(text))
    if not match:
        return text
    return text[match[-1].end() :]


def clean_reference_lines(text: str) -> list[str]:
    source_lines = text.splitlines()
    while source_lines and not normalize_space(source_lines[0]):
        source_lines.pop(0)
    while source_lines and page_header_like(source_lines[0]):
        source_lines.pop(0)
        while source_lines and not normalize_space(source_lines[0]):
            source_lines.pop(0)

    cleaned: list[str] = []
    for raw_line in source_lines:
        if skip_line(raw_line):
            continue
        line = raw_line.replace("\u00ad", "").rstrip()
        if not line.strip():
            cleaned.append("")
            continue
        for segment in split_inline_references(line):
            cleaned.append(segment)
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return cleaned


def split_inline_references(line: str) -> list[str]:
    rewritten = line
    for pattern in INLINE_REFERENCE_BREAK_PATTERNS:
        rewritten = pattern.sub("\n", rewritten)
    return [segment for segment in rewritten.splitlines() if segment.strip()]


def should_start_new_reference(current: str | None, line: str) -> bool:
    stripped = normalize_space(line)
    if not stripped:
        return False
    if re.match(r"^[,—-]", stripped) and YEAR_RE.search(stripped[:220]):
        return True
    if referenceish_line(stripped):
        return True
    if current:
        return False
    if YEAR_RE.search(stripped[:180]) and re.match(r"^[A-ZÀ-ÖØ-Ý]", stripped):
        return True
    return False


def finalize_reference(entry: str) -> str:
    collapsed = normalize_space(entry)
    collapsed = re.sub(r"\s+([,.;:])", r"\1", collapsed)
    collapsed = re.sub(r"([(\[])\s+", r"\1", collapsed)
    collapsed = re.sub(r"\s+([)\]])", r"\1", collapsed)
    return collapsed.strip(" ;")


def parse_references_from_pages(page_texts: list[str]) -> list[str]:
    lines: list[str] = []
    for idx, text in enumerate(page_texts):
        if idx == 0:
            text = trim_to_header_if_needed(text)
        lines.extend(clean_reference_lines(text))
        lines.append("")

    references: list[str] = []
    current_parts: list[str] = []
    current_text: str | None = None

    for raw_line in lines:
        stripped = normalize_space(raw_line)
        if not stripped:
            if current_parts:
                candidate = finalize_reference(" ".join(current_parts))
                if YEAR_RE.search(candidate[:220]) and len(candidate) >= 35:
                    references.append(candidate)
                current_parts = []
                current_text = None
            continue

        if should_start_new_reference(current_text, raw_line) and current_parts:
            candidate = finalize_reference(" ".join(current_parts))
            if YEAR_RE.search(candidate[:220]) and len(candidate) >= 35:
                references.append(candidate)
            current_parts = [stripped]
            current_text = stripped
            continue

        if not current_parts:
            current_parts = [stripped]
            current_text = stripped
        else:
            current_parts.append(stripped)
            current_text = finalize_reference(" ".join(current_parts))

    if current_parts:
        candidate = finalize_reference(" ".join(current_parts))
        if YEAR_RE.search(candidate[:220]) and len(candidate) >= 35:
            references.append(candidate)

    deduped_within_pdf: list[str] = []
    seen: set[str] = set()
    for ref in references:
        key = normalize_reference_for_compare(ref)
        if len(key) < 20 or key in seen:
            continue
        seen.add(key)
        deduped_within_pdf.append(ref)
    return deduped_within_pdf


def first_author_token(text: str) -> str:
    normalized = normalize_reference_for_compare(text)
    tokens = normalized.split()
    return tokens[0] if tokens else ""


class Deduper:
    def __init__(self) -> None:
        self.parent: list[int] = []

    def add(self) -> int:
        idx = len(self.parent)
        self.parent.append(idx)
        return idx

    def find(self, idx: int) -> int:
        if self.parent[idx] != idx:
            self.parent[idx] = self.find(self.parent[idx])
        return self.parent[idx]

    def union(self, left: int, right: int) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def similar_reference(left: str, right: str) -> bool:
    if left == right:
        return True
    if left in right and len(left) >= int(len(right) * 0.72):
        return True
    if right in left and len(right) >= int(len(left) * 0.72):
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.93


def dedupe_references(raw_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    indexed_rows: list[dict[str, str]] = []
    deduper = Deduper()
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)

    for row in raw_rows:
        compare = normalize_reference_for_compare(row["reference_text"])
        if not compare:
            continue
        index = deduper.add()
        normalized_row = dict(row)
        normalized_row["compare_text"] = compare
        normalized_row["year"] = YEAR_RE.search(compare).group(0) if YEAR_RE.search(compare) else ""
        normalized_row["first_author"] = first_author_token(row["reference_text"])
        indexed_rows.append(normalized_row)
        grouped[(normalized_row["first_author"], normalized_row["year"])].append(index)

    for group_indexes in grouped.values():
        for left_offset, left_idx in enumerate(group_indexes):
            left_text = indexed_rows[left_idx]["compare_text"]
            for right_idx in group_indexes[left_offset + 1 :]:
                right_text = indexed_rows[right_idx]["compare_text"]
                if similar_reference(left_text, right_text):
                    deduper.union(left_idx, right_idx)

    merged: dict[int, dict[str, object]] = {}
    for idx, row in enumerate(indexed_rows):
        root = deduper.find(idx)
        bucket = merged.setdefault(
            root,
            {
                "reference_candidates": [],
                "source_pdfs": set(),
            },
        )
        bucket["reference_candidates"].append(row["reference_text"])
        bucket["source_pdfs"].add(row["pdf_name"])

    result: list[dict[str, str]] = []
    for bucket in merged.values():
        candidates = sorted(
            bucket["reference_candidates"],
            key=lambda value: (-len(value), value),
        )
        canonical = candidates[0]
        source_pdfs = sorted(bucket["source_pdfs"])
        reference_id = hashlib.sha1(
            normalize_reference_for_compare(canonical).encode("utf-8")
        ).hexdigest()[:12]
        result.append(
            {
                "reference_id": reference_id,
                "reference_text": canonical,
                "source_pdf_count": str(len(source_pdfs)),
                "source_pdfs": " | ".join(source_pdfs),
            }
        )

    result.sort(
        key=lambda row: (
            normalize_reference_for_compare(row["reference_text"]),
            row["reference_id"],
        )
    )
    return result


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def extract_folder_references(input_dir: Path, output_dir: Path) -> dict[str, object]:
    pdf_paths = sorted(input_dir.glob("*.pdf"))
    raw_rows: list[dict[str, str]] = []
    status_rows: list[PdfStatus] = []

    for pdf_path in pdf_paths:
        pages = pdf_page_count(pdf_path)
        page_texts = {page: extract_page_text(pdf_path, page) for page in range(1, pages + 1)}
        selected_pages, method, note = detect_reference_pages(page_texts)

        if not selected_pages:
            status_rows.append(
                PdfStatus(
                    pdf_name=pdf_path.name,
                    pages=pages,
                    detected_start_page=None,
                    detected_end_page=None,
                    method=method,
                    extracted_references=0,
                    note=note,
                )
            )
            continue

        selected_texts = [page_texts[page] for page in selected_pages]
        references = parse_references_from_pages(selected_texts)

        for ref_index, reference in enumerate(references, start=1):
            raw_rows.append(
                {
                    "pdf_name": pdf_path.name,
                    "reference_index": str(ref_index),
                    "reference_text": reference,
                }
            )

        status_note = ""
        if not references:
            status_note = "reference pages detected but no clean entries parsed"
        status_rows.append(
            PdfStatus(
                pdf_name=pdf_path.name,
                pages=pages,
                detected_start_page=selected_pages[0],
                detected_end_page=selected_pages[-1],
                method=method,
                extracted_references=len(references),
                note=status_note,
            )
        )

    deduped_rows = dedupe_references(raw_rows)

    raw_output = output_dir / "development_references_by_pdf.csv"
    deduped_output = output_dir / "development_references_deduped.csv"
    status_output = output_dir / "development_reference_extraction_status.csv"
    summary_output = output_dir / "development_references_summary.json"

    write_csv(
        raw_output,
        raw_rows,
        ["pdf_name", "reference_index", "reference_text"],
    )
    write_csv(
        deduped_output,
        deduped_rows,
        ["reference_id", "reference_text", "source_pdf_count", "source_pdfs"],
    )
    write_csv(
        status_output,
        [
            {
                "pdf_name": row.pdf_name,
                "pages": str(row.pages),
                "detected_start_page": "" if row.detected_start_page is None else str(row.detected_start_page),
                "detected_end_page": "" if row.detected_end_page is None else str(row.detected_end_page),
                "method": row.method,
                "extracted_references": str(row.extracted_references),
                "note": row.note,
            }
            for row in status_rows
        ],
        [
            "pdf_name",
            "pages",
            "detected_start_page",
            "detected_end_page",
            "method",
            "extracted_references",
            "note",
        ],
    )

    summary = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "pdf_count": len(pdf_paths),
        "pdfs_with_detected_references": sum(1 for row in status_rows if row.detected_start_page is not None),
        "total_extracted_reference_rows": len(raw_rows),
        "total_deduped_references": len(deduped_rows),
        "pdfs_without_detected_references": [
            row.pdf_name for row in status_rows if row.detected_start_page is None
        ],
        "pdfs_with_zero_parsed_entries": [
            row.pdf_name for row in status_rows if row.detected_start_page is not None and row.extracted_references == 0
        ],
        "outputs": {
            "by_pdf": str(raw_output),
            "deduped": str(deduped_output),
            "status": str(status_output),
            "summary": str(summary_output),
        },
    }
    summary_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract and deduplicate reference lists from PDFs in a folder."
    )
    parser.add_argument("input_dir", type=Path, help="Folder containing PDF files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write the CSV/JSON outputs. Defaults to the input folder.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.expanduser().resolve()
    output_dir = (
        args.output_dir.expanduser().resolve() if args.output_dir is not None else input_dir
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = extract_folder_references(input_dir=input_dir, output_dir=output_dir)
    json.dump(summary, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
