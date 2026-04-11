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


ROOT = Path(__file__).resolve().parents[1]
NOTES_ROOT = ROOT / "Notes"
if not NOTES_ROOT.exists():
    NOTES_ROOT = ROOT / "Reading Notes"
REFERENCE_ROOT = ROOT / "Reference"
if not REFERENCE_ROOT.exists():
    REFERENCE_ROOT = ROOT / "reference"
REPORT_ROOT = ROOT / "_Preprocess"
DUPLICATE_ROOT = ROOT / "_Duplicates"
PENDING_JOURNAL_SOURCES_PATH = REPORT_ROOT / "crawler_next_journals.csv"
GLOBAL_BIB_NAME = "literature.bib"
GLOBAL_BIB_PATH = REFERENCE_ROOT / GLOBAL_BIB_NAME
TODAY = date.today().isoformat()
USER_AGENT = "Codex Literature Vault Sync/2.0 (mailto:no-reply@example.com)"
NOTES_FOLDER_NAME = NOTES_ROOT.name

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
NAME_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
BIB_OMIT_FIELDS = {"doi", "file"}

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

SOURCE_CODE_STOPWORDS = {
    "and",
    "for",
    "in",
    "of",
    "on",
    "the",
}

STOPWORDS = {
    "abstract",
    "across",
    "also",
    "article",
    "about",
    "after",
    "among",
    "argument",
    "been",
    "before",
    "between",
    "beyond",
    "bureaucracy",
    "capacity",
    "china",
    "courts",
    "development",
    "dissertation",
    "digital",
    "effects",
    "evidence",
    "faculty",
    "find",
    "findings",
    "first",
    "from",
    "government",
    "governance",
    "have",
    "having",
    "however",
    "institutions",
    "institutional",
    "into",
    "judicial",
    "law",
    "lawyers",
    "legal",
    "less",
    "main",
    "more",
    "paper",
    "political",
    "politics",
    "public",
    "regime",
    "regimes",
    "results",
    "rule",
    "second",
    "shows",
    "state",
    "study",
    "surveillance",
    "system",
    "than",
    "that",
    "their",
    "there",
    "these",
    "third",
    "this",
    "theory",
    "through",
    "those",
    "under",
    "using",
    "when",
    "where",
    "while",
    "which",
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
    "audit experiment": [
        r"\baudit experiment(?:s)?\b",
        r"\baudit stud(?:y|ies)\b",
    ],
    "correspondence study": [
        r"\bcorrespondence (?:study|studies|experiment|experiments|test|tests)\b",
        r"\bemail[- ]based audit experiment\b",
    ],
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
    "as": "Administrative Sciences",
    "apsr": "American Political Science Review",
    "arlss": "Annual Review of Law and Social Science",
    "arps": "Annual Review of Political Science",
    "bjps": "British Journal of Political Science",
    "bmgs": "Byzantine and Modern Greek Studies",
    "cjls": "Canadian Journal of Law and Society / La Revue Canadienne Droit et Société",
    "cq": "The China Quarterly",
    "cornell_international_law_journal": "Cornell International Law Journal",
    "cps": "Comparative Political Studies",
    "dcm": "Discourse, Context & Media",
    "democrat": "Democratization",
    "ecma": "Econometrica",
    "eeh": "Explorations in Economic History",
    "ehdr": "Economic History of Developing Regions",
    "ej": "The Economic Journal",
    "ejdr": "The European Journal of Development Research",
    "giq": "Government Information Quarterly",
    "gmc": "Global Media and Communication",
    "hofstra": "Hofstra Law Review",
    "hssc": "Humanities and Social Sciences Communications",
    "imago": "Imago Mundi",
    "im": "Information & Management",
    "io": "International Organization",
    "isq": "International Studies Quarterly",
    "itinerario": "Itinerario",
    "jde": "Journal of Development Economics",
    "jeh": "The Journal of Economic History",
    "jeg": "Journal of Economic Geography",
    "jgh": "Journal of Global History",
    "ijpor": "International Journal of Public Opinion Research",
    "jc": "Journal of Communication",
    "jcca": "Journal of Current Chinese Affairs",
    "jd": "Journal of Democracy",
    "jeas": "Journal of East Asian Studies",
    "jep": "Journal of Economic Perspectives",
    "jpipe": "Journal of Political Institutions and Political Economy",
    "jas": "The Journal of Asian Studies",
    "jcc": "Journal of Contemporary China",
    "jcr": "Journal of Conflict Resolution",
    "jeea": "Journal of the European Economic Association",
    "jpopecon": "Journal of Population Economics",
    "jrs": "Journal of Regional Science",
    "jue": "Journal of Urban Economics",
    "jlc": "Journal of Law and Courts",
    "jop": "The Journal of Politics",
    "jpart": "Journal of Public Administration Research and Theory",
    "jpe": "Journal of Political Economy",
    "jpube": "Journal of Public Economics",
    "jpubeco": "Journal of Public Economics",
    "lsi": "Law & Social Inquiry",
    "lsr": "Law & Society Review",
    "ms": "Management Science",
    "nhb": "Nature Human Behaviour",
    "pan": "Political Analysis",
    "pacai": "Proceedings of the AAAI Conference on Artificial Intelligence",
    "pi": "Policy & Internet",
    "polgeo": "Political Geography",
    "polbeh": "Political Behavior",
    "polcomm": "Political Communication",
    "poq": "Public Opinion Quarterly",
    "polgender": "Politics & Gender",
    "pnas": "Proceedings of the National Academy of Sciences",
    "pp": "Perspectives on Politics",
    "ppmr": "Public Performance & Management Review",
    "ps": "Politics & Society",
    "psrm": "Political Science Research and Methods",
    "qjps": "Quarterly Journal of Political Science",
    "qje": "Quarterly Journal of Economics",
    "jeps": "Journal of Experimental Political Science",
    "arecon": "Annual Review of Economics",
    "arpsych": "Annual Review of Psychology",
    "restat": "The Review of Economics and Statistics",
    "restud": "Review of Economic Studies",
    "arsoc": "Annual Review of Sociology",
    "rsue": "Regional Science and Urban Economics",
    "rte": "Research in Transportation Economics",
    "sej": "SSRN Electronic Journal",
    "ssh": "Social Science History",
    "wd": "World Development",
    "wpol": "World Politics",
}

JOURNAL_ABBR_ALIASES = {
    "wp": "wpol",
}

WORKING_PAPER_HINTS = {
    "cepr discussion paper",
    "discussion paper",
    "faculty research working paper",
    "job market paper",
    "manuscript",
    "mimeo",
    "nber working paper",
    "ssrn",
    "unpublished manuscript",
    "working draft",
    "working paper",
}

BOOK_PUBLISHER_HINTS = {
    "cambridge university press",
    "columbia university press",
    "cornell university press",
    "harvard university press",
    "oxford university press",
    "princeton university press",
    "routledge",
    "stanford university press",
    "university of chicago press",
    "yale university press",
}

BOOK_HINTS = {
    "book chapter",
    "edited volume",
    "handbook",
    "monograph",
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
        r"^downloaded from .*annualreviews\.org",
        r"^guest \(guest\) ip:",
        r"^published by",
        r"^working paper",
        r"^department of",
    ]
]

ARTICLE_SECTION_LABELS = {
    "article",
    "original article",
    "research article",
    "research note",
    "regular article",
    "brief report",
}

AFFILIATION_HINTS = (
    "university",
    "department",
    "school",
    "college",
    "institute",
    "centre",
    "center",
    "faculty",
    "correspondence",
    "email",
    "keywords",
    "jel",
    "contents lists available at",
    "journal homepage",
    "article info",
    "dataset link",
    "published online",
    "first published online",
    "received",
    "accepted",
    "revised",
    "acknowledg",
    "e-mail",
    "supplementary data",
    "teaching slides",
    "editor in charge",
    "data science",
)

LOCAL_VENUE_ALIASES = {
    "american political science review": "apsr",
    "american journal of political science": "ajps",
    "american j political sci": "ajps",
    "administrative sciences": "as",
    "the journal of politics": "jop",
    "journal of politics": "jop",
    "journal of public administration research and theory": "jpart",
    "british journal of political science": "bjps",
    "b j pol s": "bjps",
    "comparative political studies": "cps",
    "democratization": "democrat",
    "discourse, context & media": "dcm",
    "global media and communication": "gmc",
    "government information quarterly": "giq",
    "humanities and social sciences communications": "hssc",
    "information & management": "im",
    "information and management": "im",
    "international studies quarterly": "isq",
    "quarterly journal of political science": "qjps",
    "journal of experimental political science": "jeps",
    "the china quarterly": "cq",
    "china quarterly": "cq",
    "cornell international law journal": "cornell_international_law_journal",
    "journal of contemporary china": "jcc",
    "journal of communication": "jc",
    "journal of current chinese affairs": "jcca",
    "journal of democracy": "jd",
    "journal of east asian studies": "jeas",
    "journal of economic perspectives": "jep",
    "journal of political institutions and political economy": "jpipe",
    "world politics": "wpol",
    "international organization": "io",
    "canadian journal of law and society": "cjls",
    "canadian journal of law and society / la revue canadienne droit et societe": "cjls",
    "la revue canadienne droit et societe": "cjls",
    "hofstra law review": "hofstra",
    "the journal of asian studies": "jas",
    "journal of asian studies": "jas",
    "management science": "ms",
    "nature human behaviour": "nhb",
    "political analysis": "pan",
    "political geography": "polgeo",
    "political behavior": "polbeh",
    "political science research and methods": "psrm",
    "policy & internet": "pi",
    "proceedings of the aaai conference on artificial intelligence": "pacai",
    "proceedings of the national academy of sciences": "pnas",
    "proceedings of the national academy of sciences of the united states of america": "pnas",
    "perspectives on politics": "pp",
    "public performance & management review": "ppmr",
    "politics & society": "ps",
    "public opinion quarterly": "poq",
    "annual review of political science": "arps",
    "annual review of psychology": "arpsych",
    "annual review of economics": "arecon",
    "annual review of sociology": "arsoc",
    "annurev polisci": "arps",
    "american economic review": "aer",
    "american economic journal applied economics": "aejapplied",
    "american economic journal economic policy": "aejpolicy",
    "american economic journal macroeconomics": "aejmacro",
    "american economic journal microeconomics": "aejmicro",
    "journal of political economy": "jpe",
    "journal of public economics": "jpubeco",
    "journal of development economics": "jde",
    "journal of regional science": "jrs",
    "journal of population economics": "jpopecon",
    "journal of conflict resolution": "jcr",
    "journal of global history": "jgh",
    "journal of economic geography": "jeg",
    "econometrica": "ecma",
    "the quarterly journal of economics": "qje",
    "quarterly journal of economics": "qje",
    "the review of economic studies": "restud",
    "review of economic studies": "restud",
    "the review of economics and statistics": "restat",
    "review of economics and statistics": "restat",
    "journal of the european economic association": "jeea",
    "the economic journal": "ej",
    "economic journal": "ej",
    "explorations in economic history": "eeh",
    "economic history of developing regions": "ehdr",
    "the european journal of development research": "ejdr",
    "european journal of development research": "ejdr",
    "imago mundi": "imago",
    "itinerario": "itinerario",
    "regional science and urban economics": "rsue",
    "research in transportation economics": "rte",
    "ssrn electronic journal": "sej",
    "social science history": "ssh",
    "world development": "wd",
    "byzantine and modern greek studies": "bmgs",
}

DOI_JOURNAL_PATTERNS = [
    (re.compile(r"10\.1257/aer\.", re.IGNORECASE), "aer"),
    (re.compile(r"10\.1111/ajps\.", re.IGNORECASE), "ajps"),
    (re.compile(r"10\.1017/psrm\.", re.IGNORECASE), "psrm"),
    (re.compile(r"10\.1017/s1743923x", re.IGNORECASE), "polgender"),
    (re.compile(r"10\.1093/jopart/", re.IGNORECASE), "jpart"),
    (re.compile(r"10\.1093/ijpor/", re.IGNORECASE), "ijpor"),
    (re.compile(r"10\.1017/pan\.|10\.1093/pan/", re.IGNORECASE), "pan"),
    (re.compile(r"10\.1073/pnas\.", re.IGNORECASE), "pnas"),
    (re.compile(r"10\.1007/s11109-", re.IGNORECASE), "polbeh"),
    (re.compile(r"10\.1093/poq/", re.IGNORECASE), "poq"),
    (re.compile(r"10\.1017/s00071234", re.IGNORECASE), "bjps"),
    (re.compile(r"10\.1017/s00030554", re.IGNORECASE), "apsr"),
    (re.compile(r"10\.1093/jeea/", re.IGNORECASE), "jeea"),
    (re.compile(r"10\.1016/j\.jde\.", re.IGNORECASE), "jde"),
    (re.compile(r"10\.1016/j\.eeh\.", re.IGNORECASE), "eeh"),
    (re.compile(r"10\.1016/j\.jue\.", re.IGNORECASE), "jue"),
    (re.compile(r"10\.1016/j\.jpubeco\.", re.IGNORECASE), "jpubeco"),
    (re.compile(r"10\.1016/j\.polgeo\.", re.IGNORECASE), "polgeo"),
    (re.compile(r"10\.1016/j\.regsciurbeco\.", re.IGNORECASE), "rsue"),
    (re.compile(r"10\.1016/j\.retrec\.", re.IGNORECASE), "rte"),
    (re.compile(r"10\.1017/s00220507", re.IGNORECASE), "jeh"),
    (re.compile(r"10\.1017/s00208183", re.IGNORECASE), "io"),
    (re.compile(r"10\.1017/s00219118", re.IGNORECASE), "jas"),
    (re.compile(r"10\.1017/s01651153", re.IGNORECASE), "itinerario"),
    (re.compile(r"10\.1017/s17400228", re.IGNORECASE), "jgh"),
    (re.compile(r"10\.1017/ssh\.", re.IGNORECASE), "ssh"),
    (re.compile(r"10\.3982/ecta", re.IGNORECASE), "ecma"),
    (re.compile(r"10\.1093/jeg/", re.IGNORECASE), "jeg"),
    (re.compile(r"10\.1111/ecoj\.|10\.1093/ej/", re.IGNORECASE), "ej"),
    (re.compile(r"10\.1111/jors\.", re.IGNORECASE), "jrs"),
    (re.compile(r"10\.1146/annurev-economics", re.IGNORECASE), "arecon"),
    (re.compile(r"10\.1146/annurev-polisci", re.IGNORECASE), "arps"),
    (re.compile(r"10\.1146/annurev-psych", re.IGNORECASE), "arpsych"),
    (re.compile(r"10\.1146/annurev-soc|10\.1146/annurev\.soc", re.IGNORECASE), "arsoc"),
    (re.compile(r"10\.1111/ajps", re.IGNORECASE), "ajps"),
    (re.compile(r"10\.1177/00220027", re.IGNORECASE), "jcr"),
    (re.compile(r"10\.1179/byz\.", re.IGNORECASE), "bmgs"),
    (re.compile(r"10\.3138/cjls\.", re.IGNORECASE), "cjls"),
    (re.compile(r"10\.1007/s00148-", re.IGNORECASE), "jpopecon"),
    (re.compile(r"10\.1080/03085694\.", re.IGNORECASE), "imago"),
    (re.compile(r"10\.1080/09578819", re.IGNORECASE), "ejdr"),
    (re.compile(r"10\.1080/20780389\.", re.IGNORECASE), "ehdr"),
]

LOCAL_DOI_METADATA_OVERRIDES = {
    "10.1017/s0007123413000203": {
        "title": "Online Social Media and Political Awareness in Authoritarian Regimes",
        "authors": ["Ora John Reuter", "David Szakonyi"],
        "year": "2013",
        "venue": "British Journal of Political Science",
        "journal_abbr": "bjps",
    },
    "10.1257/aer.20211218": {
        "title": "Social Media and Mental Health",
        "authors": ["Luca Braghieri", "Ro’ee Levy", "Alexey Makarin"],
        "year": "2022",
        "venue": "American Economic Review",
        "journal_abbr": "aer",
    },
    "10.1017/s0003055423001053": {
        "title": "Social Media, Social Control, and the Politics of Public Shaming",
        "authors": ["Jennifer Forestal"],
        "year": "2024",
        "venue": "American Political Science Review",
        "journal_abbr": "apsr",
    },
    "10.1017/s000305542300134x": {
        "title": "Toxic Speech and Limited Demand for Content Moderation on Social Media",
        "authors": ["Franziska Pradel", "Jan Zilinsky", "Spyros Kosmidis", "Yannis Theocharis"],
        "year": "2024",
        "venue": "American Political Science Review",
        "journal_abbr": "apsr",
    },
    "10.1093/jeea/jvaa045": {
        "title": "Fanning the Flames of Hate: Social Media and Hate Crime",
        "authors": ["Karsten Müller", "Carlo Schwarz"],
        "year": "2021",
        "venue": "Journal of the European Economic Association",
        "journal_abbr": "jeea",
    },
    "10.1016/j.jdeveco.2026.103784": {
        "title": "The spread of (mis)information: A social media experiment in Pakistan",
        "authors": ["Sarojini Hirshleifer", "Mustafa Naseem", "Agha Ali Raza", "Arman Rezaee"],
        "year": "2026",
        "venue": "Journal of Development Economics",
        "journal_abbr": "jde",
    },
    "10.1016/j.jpubeco.2026.105589": {
        "title": "Ranking for engagement: How social media algorithms fuel misinformation and polarization",
        "authors": ["Fabrizio Germano"],
        "year": "2026",
        "venue": "Journal of Public Economics",
        "journal_abbr": "jpubeco",
    },
    "10.1017/s0003055422000508": {
        "title": "“This Hearing Should Be Flipped”: Democratic Spectatorship, Social Media, and the Problem of Demagogic Candor",
        "authors": ["Boris Litvin"],
        "year": "2023",
        "venue": "American Political Science Review",
        "journal_abbr": "apsr",
    },
    "10.1017/s0007123421000594": {
        "title": "Social Media and Press Freedom",
        "authors": ["Korhan Kocak", "Özgür Kıbrıs"],
        "year": "2023",
        "venue": "British Journal of Political Science",
        "journal_abbr": "bjps",
    },
    "10.1146/annurev-polisci-033123015559": {
        "title": "Accountability in Developing Democracies: The Impact of the Internet, Social Media, and Polarization",
        "authors": ["Horacio Larreguy", "Pia J. Raffler"],
        "year": "2025",
        "venue": "Annual Review of Political Science",
        "journal_abbr": "arps",
    },
    "10.1017/xps.2024.15": {
        "title": "Introducing the Visual Conjoint, with an Application to Candidate Evaluation on Social Media",
        "authors": ["Alessandro Vecchiato", "Kevin Munger"],
        "year": "2025",
        "venue": "Journal of Experimental Political Science",
        "journal_abbr": "jeps",
    },
    "10.1017/pan.2024.19": {
        "title": "News Sharing on Social Media: Mapping the Ideology of News Media, Politicians, and the Mass Public",
        "authors": ["Gregory Eady", "Richard Bonneau", "Joshua A. Tucker", "Jonathan Nagler"],
        "year": "2025",
        "venue": "Political Analysis",
        "journal_abbr": "pan",
    },
    "10.1086/702233": {
        "title": "Media, Public Opinion, and Foreign Policy in the Age of Social Media",
        "authors": ["Matthew A. Baum", "Philip B. K. Potter"],
        "year": "2019",
        "venue": "The Journal of Politics",
        "journal_abbr": "jop",
    },
    "10.1016/j.jpubeco.2025.105345": {
        "title": "Debunking “fake news” on social media: Immediate and short-term effects of fact-checking and media literacy interventions",
        "authors": ["Lara Marie Berger", "Anna Kerkhof", "Felix Mindl", "Johannes Münster"],
        "year": "2025",
        "venue": "Journal of Public Economics",
        "journal_abbr": "jpubeco",
    },
    "10.1017/s0003055417000144": {
        "title": "How the Chinese Government Fabricates Social Media Posts for Strategic Distraction, Not Engaged Argument",
        "authors": ["Gary King", "Jennifer Pan", "Margaret E. Roberts"],
        "year": "2017",
        "venue": "American Political Science Review",
        "journal_abbr": "apsr",
    },
    "10.1017/s0007123420000198": {
        "title": "Political Knowledge and Misinformation in the Era of Social Media: Evidence From the 2015 UK Election",
        "authors": ["Kevin Munger", "Patrick J. Egan", "Jonathan Nagler", "Jonathan Ronen", "Joshua Tucker"],
        "year": "2022",
        "venue": "British Journal of Political Science",
        "journal_abbr": "bjps",
    },
    "10.1086/703490": {
        "title": "Social Media, Political Science, and Democracy",
        "authors": ["Kevin Munger"],
        "year": "2019",
        "venue": "The Journal of Politics",
        "journal_abbr": "jop",
    },
    "10.1017/s0007123424000450": {
        "title": "Estimating Ideal Points of British MPs Through Their Social Media Followership",
        "authors": ["Conor Gaughan"],
        "year": "2024",
        "venue": "British Journal of Political Science",
        "journal_abbr": "bjps",
    },
    "10.1017/s0003055419000352": {
        "title": "Who Leads? Who Follows? Measuring Issue Attention and Agenda Setting by Legislators and the Mass Public Using Social Media Data",
        "authors": ["Pablo Barberá", "Andreu Casas", "Jonathan Nagler", "Patrick J. Egan", "Richard Bonneau", "John T. Jost", "Joshua A. Tucker"],
        "year": "2019",
        "venue": "American Political Science Review",
        "journal_abbr": "apsr",
    },
    "10.1017/s0007123416000612": {
        "title": "A Manifesto, in 140 Characters or Fewer: Social Media as a Tool of Rebel Diplomacy",
        "authors": ["Benjamin T. Jones", "Eleonora Mattiacci"],
        "year": "2017",
        "venue": "British Journal of Political Science",
        "journal_abbr": "bjps",
    },
    "10.1017/s0007123418000194": {
        "title": "Launching Revolution: Social Media and the Egyptian Uprising’s First Movers",
        "authors": ["Killian Clarke", "Korhan Kocak"],
        "year": "2020",
        "venue": "British Journal of Political Science",
        "journal_abbr": "bjps",
    },
    "10.1016/j.jpubeco.2022.104735": {
        "title": "Do social media ads matter for political behavior? A field experiment",
        "authors": ["George Beknazar-Yuzbashev", "Mateusz Stalinski"],
        "year": "2022",
        "venue": "Journal of Public Economics",
        "journal_abbr": "jpubeco",
    },
    "10.1086/739664": {
        "title": "A Male Hostility Spiral? Polarized Communication among Political Elites on Social Media",
        "authors": ["Albert Wendsjö", "Hanna Bäck", "Andrej Kokkonen"],
        "year": "2025",
        "venue": "The Journal of Politics",
        "journal_abbr": "jop",
    },
    "10.1086/716949": {
        "title": "Fighting Propaganda with Censorship: A Study of the Ukrainian Ban on Russian Social Media",
        "authors": ["Yevgeniy Golovchenko"],
        "year": "2022",
        "venue": "The Journal of Politics",
        "journal_abbr": "jop",
    },
    "10.1086/733007": {
        "title": "Using Social Media to Respond to Negative Polls: Politicians’ Issue Responsiveness on Facebook",
        "authors": ["Helene Helboe Pedersen", "Henrik Bech Seeberg"],
        "year": "2025",
        "venue": "The Journal of Politics",
        "journal_abbr": "jop",
    },
    "10.1017/psrm.2018.68": {
        "title": "Missing the Target? Using Surveys to Validate Social Media Ad Targeting",
        "authors": ["Michael W. Sances"],
        "year": "2021",
        "venue": "Political Science Research and Methods",
        "journal_abbr": "psrm",
    },
    "10.1093/ej/ueaf047": {
        "title": "Correlation Neglect on Social Media: Effects on Civil Service Applications in China",
        "authors": ["Yihong Huang", "Yixi Jiang", "Ziqi Lu"],
        "year": "2025",
        "venue": "The Economic Journal",
        "journal_abbr": "ej",
    },
    "10.1596/1813-9450-11071": {
        "title": "Road Investment and Violence in DRC: Perishable Peace Dividends",
        "authors": ["Mathilde Lebrand", "Hannes Mueller", "Peer Schouten", "Jevgenijs Steinbuks"],
        "year": "2025",
        "venue": "World Bank Policy Research Working Paper",
        "journal_abbr": "wp",
    },
    "10.1146/annurev-polisci-052715111917": {
        "title": "The Electoral Consequences of Corruption",
        "authors": ["Catherine E. De Vries", "Hector Solaz"],
        "year": "2017",
        "venue": "Annual Review of Political Science",
        "journal_abbr": "arps",
        "doi": "10.1146/annurev-polisci-052715-111917",
        "url": "https://doi.org/10.1146/annurev-polisci-052715-111917",
        "volume": "20",
        "pages": "391-408",
        "publisher": "Annual Reviews",
    },
    "10.1146/annurev-polisci-052715-111917": {
        "title": "The Electoral Consequences of Corruption",
        "authors": ["Catherine E. De Vries", "Hector Solaz"],
        "year": "2017",
        "venue": "Annual Review of Political Science",
        "journal_abbr": "arps",
        "doi": "10.1146/annurev-polisci-052715-111917",
        "url": "https://doi.org/10.1146/annurev-polisci-052715-111917",
        "volume": "20",
        "pages": "391-408",
        "publisher": "Annual Reviews",
    },
    "10.2139/ssrn.6166866": {
        "title": "Local Knowledge and State Building: Evidence from Chinese Gazeteers",
        "authors": ["Xinxian Li", "Ningxi Liu", "Chicheng Ma"],
        "year": "2026",
        "venue": "CQH Working Paper Series",
        "journal_abbr": "wp",
        "publisher": "CQH Working Paper Series",
        "url": "https://doi.org/10.2139/ssrn.6166866",
    },
    "10.2139/ssrn.4424060": {
        "title": "Political Repression and Nation-building",
        "authors": ["Peiyuan Li"],
        "year": "2025",
        "venue": "CQH Working Paper Series",
        "journal_abbr": "wp",
        "publisher": "CQH Working Paper Series",
        "url": "https://doi.org/10.2139/ssrn.4424060",
    },
    "10.2139/ssrn.4508254": {
        "title": "The Economics of Mobilizing Free Riders: Evidence from the Chinese Civil War 1945-1949",
        "authors": ["Peiyuan Li"],
        "year": "2026",
        "venue": "CQH Working Paper Series",
        "journal_abbr": "wp",
        "publisher": "CQH Working Paper Series",
        "url": "https://doi.org/10.2139/ssrn.4508254",
    },
    "10.2139/ssrn.5195597": {
        "title": "Christian Missionaries and International Trade, 1580-1936",
        "authors": ["Zhiwu Chen", "Xinhao Li", "Chicheng Ma"],
        "year": "2025",
        "venue": "CQH Working Paper Series",
        "journal_abbr": "wp",
        "publisher": "Centre for Quantitative History, HKU Business School",
        "url": "https://doi.org/10.2139/ssrn.5195597",
    },
    "10.2139/ssrn.5270912": {
        "title": "Telegraph, Media, and State Information Capacity: Evidence from Late Imperial China",
        "authors": ["Yu Hao", "Yuxiang Wang"],
        "year": "2025",
        "venue": "CQH Working Paper Series",
        "journal_abbr": "wp",
        "publisher": "Centre for Quantitative History, HKU Business School",
        "url": "https://doi.org/10.2139/ssrn.5270912",
    },
    "10.2139/ssrn.4932600": {
        "title": "Article-Level Slant and Polarization of News Consumption on Social Media",
        "authors": ["Luca Braghieri", "Sarah Eichmeyer", "Ro'ee Levy", "Markus Mobius", "Jacob Steinhardt", "Ruiqi Zhong"],
        "year": "2025",
        "venue": "Working paper",
        "journal_abbr": "wp",
        "url": "https://doi.org/10.2139/ssrn.4932600",
    },
    "10.48550/arxiv.2404.01566": {
        "title": "Heterogeneous Treatment Effects and Causal Mechanisms",
        "authors": ["Jiawei Fu", "Tara Slough"],
        "year": "2026",
        "venue": "American Political Science Review",
        "journal_abbr": "apsr",
        "doi": "10.1017/S0003055426101580",
        "url": "https://doi.org/10.1017/S0003055426101580",
        "publisher": "Cambridge University Press",
    },
    "10.3386/w35011": {
        "title": "Knowledge Spillovers and Local Outcomes: An Existence Proof from the Establishment of the National Labs",
        "authors": ["Susan Helper", "Resem Makan", "Daniel W. Shoag"],
        "year": "2026",
        "venue": "NBER Working Paper",
        "journal_abbr": "wp",
        "publisher": "National Bureau of Economic Research",
        "url": "https://doi.org/10.3386/w35011",
    },
}
AUDIT_TAG_PATTERNS = {
    "audit-study": [
        r"\baudit experiment(?:s)?\b",
        r"\baudit stud(?:y|ies)\b",
    ],
    "correspondence-study": [
        r"\bcorrespondence (?:study|studies|experiment|experiments|test|tests)\b",
        r"\bemail correspondence study\b",
        r"\bemail[- ]based audit experiment\b",
    ],
}

LEGACY_NOTE_REDIRECTS = {
    "Developing Country Bureaucracy and Accountability": {
        "zeitlin_2017_misc": "leaver_2021_aer",
    },
    "Lawyers and Courts": {
        "ginsburg_2009_misc": "ginsburg_2008_book",
        "guo_2016_misc": "pils_2015_book",
    },
    "Method": {
        "fu_2024_misc": "fu_2025_wp",
        "xia_2026_expert_systems_with_applications": "xia_2026_wp",
        "zhang_2026_misc": "zhang_2026_wp",
    },
}

LEGACY_COLLECTION_ALIASES = {
    "Information": {
        "pdf_dirs": ["Social_Media", "Social Media"],
        "note_dirs": ["Social_Media", "Social Media"],
    },
}


@dataclass(frozen=True)
class CollectionSpec:
    pdf_dir: str
    note_dir: str
    category: str
    source: str = "explicit"

    @property
    def pdf_path(self) -> Path:
        return ROOT / self.pdf_dir

    @property
    def note_path(self) -> Path:
        return NOTES_ROOT / self.note_dir


EXPLICIT_COLLECTIONS = {
    "Authoritarianism": CollectionSpec(
        "Authoritarianism",
        "Authoritarian Politics",
        "Authoritarian Politics",
    ),
    "Bureaucracy": CollectionSpec(
        "Bureaucracy",
        "Developing Country Bureaucracy and Accountability",
        "Developing Country Bureaucracy and Accountability",
    ),
    "Dissertation": CollectionSpec(
        "Dissertation",
        "Good Dissertation",
        "Good Dissertation",
    ),
    "Information": CollectionSpec(
        "Information",
        "China Censorship Propaganda and Public Opinion",
        "China Censorship Propaganda and Public Opinion",
    ),
    "Law": CollectionSpec(
        "Law",
        "Lawyers and Courts",
        "Lawyers and Courts",
    ),
    "Method": CollectionSpec("Method", "Method", "Method"),
    "RCT": CollectionSpec("RCT", "RCT", "RCT"),
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


def normalize_person_name(text: str) -> str:
    return normalize_space(html.unescape(text))


PLACEHOLDER_AUTHOR_SLUGS = {
    "anonymous",
    "anon",
    "unknown",
    "unknown_author",
    "author",
    "authors",
    "metadata_unresolved",
}

TITLE_FALLBACK_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
    "without",
}


def is_placeholder_author(name: str) -> bool:
    slug = slugify(normalize_person_name(name)).replace("-", "_")
    if not slug:
        return True
    return slug in PLACEHOLDER_AUTHOR_SLUGS


def cleaned_authors(values: Any) -> list[str]:
    authors: list[str] = []
    seen: set[str] = set()
    for value in ensure_list(values):
        author = normalize_person_name(str(value))
        if not author or is_placeholder_author(author):
            continue
        key = normalize_title(author)
        if not key or key in seen:
            continue
        seen.add(key)
        authors.append(author)
    return authors


def title_fallback_slug(title: str, fallback: str = "source") -> str:
    ascii_title = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii")
    for token in re.findall(r"[A-Za-z0-9]+", ascii_title):
        normalized = slugify(token).replace("-", "_")
        if (
            normalized
            and normalized not in TITLE_FALLBACK_STOPWORDS
            and normalized not in PLACEHOLDER_AUTHOR_SLUGS
            and not re.fullmatch(r"(19|20)\d{2}", normalized)
        ):
            return normalized
    fallback_slug = slugify(fallback).replace("-", "_")
    return fallback_slug or "source"


def normalize_name_token(token: str, lowercase_prefixes: bool) -> str:
    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        if len(word) == 1:
            return word.upper()
        if lowercase_prefixes and word.lower() in SURNAME_PREFIXES:
            return word.lower()
        if word.isupper():
            return word[0].upper() + word[1:].lower()
        return word

    return NAME_WORD_RE.sub(replace, token)


def person_prefix_token(token: str) -> str:
    letters = "".join(char for char in token if char.isalpha())
    return letters.lower()


def format_bibtex_person_name(name: str) -> str:
    name = normalize_person_name(name)
    if not name:
        return ""
    if name.startswith("{") and name.endswith("}"):
        return name
    if "," in name:
        family, given = [normalize_space(part) for part in name.split(",", 1)]
        family = " ".join(normalize_name_token(token, lowercase_prefixes=True) for token in family.split())
        given = " ".join(normalize_name_token(token, lowercase_prefixes=False) for token in given.split())
        return f"{family}, {given}" if given else family
    tokens = name.split()
    if len(tokens) == 1:
        return normalize_name_token(tokens[0], lowercase_prefixes=True)
    family_tokens = [tokens[-1]]
    given_tokens = tokens[:-1]
    if len(tokens) >= 2 and person_prefix_token(tokens[-2]) in SURNAME_PREFIXES:
        family_tokens = [tokens[-2], tokens[-1]]
        given_tokens = tokens[:-2]
    family = " ".join(normalize_name_token(token, lowercase_prefixes=True) for token in family_tokens)
    given = " ".join(normalize_name_token(token, lowercase_prefixes=False) for token in given_tokens)
    return f"{family}, {given}" if given else family


def format_bibtex_author_list(authors: list[Any]) -> str:
    formatted = [format_bibtex_person_name(str(author)) for author in authors if format_bibtex_person_name(str(author))]
    return " and ".join(formatted)


def normalize_bib_pages(value: str) -> str:
    pages = normalize_space(value)
    return re.sub(r"(?<=\d)\s*[–—-]\s*(?=\d)", "--", pages)


def meaningful_bib_url(metadata: dict[str, Any], entry_type: str) -> str:
    if entry_type not in {"techreport", "misc"}:
        return ""
    url = normalize_space(str(metadata.get("url") or ""))
    doi = normalize_space(str(metadata.get("doi") or "")).lower()
    if not url:
        return ""
    normalized_url = url.lower().rstrip("/")
    doi_urls = {
        f"https://doi.org/{doi}".rstrip("/"),
        f"http://doi.org/{doi}".rstrip("/"),
        f"https://dx.doi.org/{doi}".rstrip("/"),
        f"http://dx.doi.org/{doi}".rstrip("/"),
    }
    if doi and normalized_url in doi_urls:
        return ""
    return url


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
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text[match.end() :]
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
            spec = CollectionSpec(child.name, note_dir, note_dir, source="auto")
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
        aliases = LEGACY_COLLECTION_ALIASES.get(spec.pdf_dir, {})
        for alias in aliases.get("pdf_dirs", []):
            mapping[alias] = spec.pdf_dir
        for alias in aliases.get("note_dirs", []):
            mapping[alias] = spec.pdf_dir
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


def build_note_index(collections: list[CollectionSpec]) -> dict[str, Any]:
    canonical_dirs: dict[str, str] = {}
    stems_by_dir: dict[str, list[str]] = {}
    exact_paths: dict[str, str] = {}
    for spec in collections:
        note_paths = list_source_notes(spec.note_path)
        stems = sorted(note_paths)
        canonical_dir = f"{NOTES_FOLDER_NAME}/{spec.note_dir}"
        aliases = {
            canonical_dir,
            f"Notes/{spec.note_dir}",
            f"Reading Notes/{spec.note_dir}",
            spec.note_dir,
        }
        legacy_aliases = LEGACY_COLLECTION_ALIASES.get(spec.pdf_dir, {})
        for alias_dir in legacy_aliases.get("note_dirs", []):
            aliases.update(
                {
                    f"{NOTES_FOLDER_NAME}/{alias_dir}",
                    f"Notes/{alias_dir}",
                    f"Reading Notes/{alias_dir}",
                    alias_dir,
                }
            )
        for alias in aliases:
            canonical_dirs[alias] = canonical_dir
            stems_by_dir[alias] = stems
        for stem, note_path in note_paths.items():
            frontmatter, _ = load_note(note_path)
            stem_aliases = [stem]
            for alias_value in ensure_list(frontmatter.get("aliases")):
                alias_text = normalize_space(str(alias_value))
                if not alias_text or "/" in alias_text:
                    continue
                stem_aliases.append(alias_text)
            for alias_stem in unique_preserve_order(stem_aliases):
                for alias in aliases:
                    exact_paths[f"{alias}/{alias_stem}"] = f"{canonical_dir}/{stem}"
                    exact_paths[f"{alias}/{alias_stem}.md"] = f"{canonical_dir}/{stem}"
        for stem in stems:
            for alias in aliases:
                exact_paths[f"{alias}/{stem}"] = f"{canonical_dir}/{stem}"
                exact_paths[f"{alias}/{stem}.md"] = f"{canonical_dir}/{stem}"
    return {
        "canonical_dirs": canonical_dirs,
        "stems_by_dir": stems_by_dir,
        "exact_paths": exact_paths,
    }


def best_fuzzy_stem_match(stems: list[str], missing_stem: str) -> str | None:
    if not stems:
        return None
    parsed_missing = parse_stem(missing_stem)
    filtered: list[str] = []
    for stem in stems:
        parsed_candidate = parse_stem(stem)
        if parsed_missing["author"] and parsed_candidate["author"] and parsed_candidate["author"] != parsed_missing["author"]:
            continue
        if parsed_missing["year"] and parsed_candidate["year"] and parsed_candidate["year"] != parsed_missing["year"]:
            continue
        filtered.append(stem)
    candidates = filtered or stems
    best = ""
    best_score = 0.0
    for stem in candidates:
        score = SequenceMatcher(None, missing_stem, stem).ratio()
        if score > best_score:
            best = stem
            best_score = score
    return best if best_score >= 0.74 else None


def canonicalize_note_target(target: str, note_index: dict[str, Any]) -> str | None:
    raw = target.replace("\\", "/").strip()
    if raw in note_index["exact_paths"]:
        return note_index["exact_paths"][raw]
    if raw.endswith(".md") and raw[:-3] in note_index["exact_paths"]:
        return note_index["exact_paths"][raw[:-3]]
    raw_no_ext = raw[:-3] if raw.endswith(".md") else raw
    if "/" not in raw_no_ext:
        return None
    parent, stem = raw_no_ext.rsplit("/", 1)
    canonical_parent = note_index["canonical_dirs"].get(parent)
    stems = note_index["stems_by_dir"].get(parent, [])
    if canonical_parent and stem in stems:
        return f"{canonical_parent}/{stem}"
    fuzzy = best_fuzzy_stem_match(stems, stem)
    if canonical_parent and fuzzy:
        return f"{canonical_parent}/{fuzzy}"
    return None


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
        proc = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=12,
        )
        title = ""
        author = ""
        for line in proc.stdout.splitlines():
            if line.startswith("Title:"):
                title = normalize_space(line.split(":", 1)[1])
            elif line.startswith("Author:"):
                author = normalize_space(line.split(":", 1)[1])
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
    if type_name in {"posted-content", "report"}:
        return "techreport"
    if type_name == "dissertation" or collection_name == "Good Dissertation":
        return "phdthesis"
    return "misc"


def canonical_journal_abbr(abbr: str, venue: str = "") -> str:
    abbr = normalize_space(abbr).lower()
    if not abbr:
        return ""
    venue_norm = normalize_title(venue)
    if abbr == "wp":
        return "wpol" if "world politics" in venue_norm else "wp"
    return JOURNAL_ABBR_ALIASES.get(abbr, abbr)


def infer_journal_abbr(venue: str, fallback: str = "") -> str:
    fallback = canonical_journal_abbr(fallback, venue)
    if fallback and fallback in KNOWN_JOURNALS:
        return fallback
    normalized = normalize_title(venue)
    if not normalized:
        return fallback
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
        ("journal of contemporary china", "jcc"),
        ("journal of political economy", "jpe"),
        ("journal of development economics", "jde"),
        ("journal of the european economic association", "jeea"),
        ("the economic journal", "ej"),
        ("econometrica", "ecma"),
        ("quarterly journal of political science", "qjps"),
        ("quarterly journal of economics", "qje"),
        ("journal of experimental political science", "jeps"),
        ("british journal of political science", "bjps"),
        ("comparative political studies", "cps"),
        ("world politics", "wpol"),
        ("international organization", "io"),
        ("political analysis", "pan"),
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
    return fallback


def fallback_journal_slug(venue: str) -> str:
    venue = normalize_space(html.unescape(venue))
    if not venue:
        return ""
    return slugify(venue).replace("-", "_")


def suggested_source_code(venue: str) -> str:
    ascii_venue = unicodedata.normalize("NFKD", html.unescape(venue or "")).encode("ascii", "ignore").decode("ascii")
    words = [word for word in re.findall(r"[A-Za-z0-9]+", ascii_venue) if word.lower() not in SOURCE_CODE_STOPWORDS]
    acronym = "".join(word[0] for word in words if word)
    if 2 <= len(acronym) <= 8:
        return acronym.upper()
    compact = re.sub(r"[^A-Za-z0-9]+", "", ascii_venue).upper()
    return (compact[:8] or "MISC")


def source_tag_slug(metadata: dict[str, Any], fallback_abbr: str, collection_name: str) -> str:
    venue = normalize_space(str(metadata.get("venue") or ""))
    known = infer_journal_abbr(venue, str(metadata.get("journal_abbr") or fallback_abbr or ""))
    if known and known in KNOWN_JOURNALS:
        return known
    entry_type = infer_entry_type(metadata, collection_name)
    if entry_type == "article" and venue:
        return fallback_journal_slug(venue)
    return canonical_journal_abbr(fallback_abbr, venue)


def working_paper_like(metadata: dict[str, Any]) -> bool:
    entry_type = normalize_space(str(metadata.get("entry_type") or "")).lower()
    if entry_type == "techreport":
        return True
    combined = normalize_title(
        " ".join(
            part
            for part in [
                normalize_space(str(metadata.get("venue") or "")),
                normalize_space(str(metadata.get("publisher") or "")),
                normalize_space(str(metadata.get("note") or "")),
                normalize_space(str(metadata.get("title") or "")),
            ]
            if part
        )
    )
    return any(hint in combined for hint in WORKING_PAPER_HINTS)


def book_like(metadata: dict[str, Any]) -> bool:
    entry_type = normalize_space(str(metadata.get("entry_type") or "")).lower()
    combined = normalize_title(
        " ".join(
            part
            for part in [
                normalize_space(str(metadata.get("venue") or "")),
                normalize_space(str(metadata.get("publisher") or "")),
                normalize_space(str(metadata.get("note") or "")),
            ]
            if part
        )
    )
    if "book chapter" in combined or ("chapter" in combined and "working paper" not in combined):
        return True
    if any(hint in combined for hint in BOOK_PUBLISHER_HINTS):
        return True
    if entry_type in {"book", "incollection"} and ("press" in combined or "routledge" in combined):
        return True
    return False


def infer_entry_type(metadata: dict[str, Any], collection_name: str) -> str:
    entry_type = normalize_space(str(metadata.get("entry_type") or "")).lower()
    if collection_name == "Good Dissertation":
        return "phdthesis"

    venue = normalize_space(str(metadata.get("venue") or ""))
    journal_abbr = infer_journal_abbr(venue, str(metadata.get("journal_abbr") or ""))
    if journal_abbr and journal_abbr in KNOWN_JOURNALS:
        return "article"
    if entry_type == "article":
        return "article"
    if working_paper_like(metadata):
        return "techreport"
    if book_like(metadata):
        combined = normalize_title(
            " ".join(
                part
                for part in [
                    normalize_space(str(metadata.get("venue") or "")),
                    normalize_space(str(metadata.get("publisher") or "")),
                    normalize_space(str(metadata.get("note") or "")),
                ]
                if part
            )
        )
        if entry_type == "incollection" or "book chapter" in combined or "chapter" in combined:
            return "incollection"
        return "book"
    if venue and any(token in venue.lower() for token in ["university", "school", "department"]):
        return "phdthesis"
    if entry_type in {"article", "phdthesis", "techreport"}:
        return entry_type
    return "misc"


def classify_name_suffix(metadata: dict[str, Any], fallback_abbr: str, collection_name: str) -> str:
    venue = normalize_space(str(metadata.get("venue") or ""))
    journal_abbr = infer_journal_abbr(venue, str(metadata.get("journal_abbr") or fallback_abbr or ""))
    if journal_abbr and journal_abbr in KNOWN_JOURNALS:
        return journal_abbr

    legacy_or_manual_abbr = canonical_journal_abbr(fallback_abbr, venue)
    if legacy_or_manual_abbr == "wp":
        return "wp"

    if normalize_space(str(metadata.get("entry_type") or "")).lower() == "article" and venue:
        return fallback_journal_slug(venue) or "misc"
    if working_paper_like(metadata):
        return "wp"
    if book_like(metadata):
        return "book"
    entry_type = infer_entry_type(metadata, collection_name)
    if entry_type == "techreport":
        return "wp"
    if entry_type == "article" and venue:
        return fallback_journal_slug(venue) or "misc"
    return "misc"


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


def infer_audit_tags(*chunks: str) -> list[str]:
    combined = " ".join(chunk for chunk in chunks if chunk)
    tags: list[str] = []
    for label, patterns in AUDIT_TAG_PATTERNS.items():
        if any(re.search(pattern, combined, re.IGNORECASE) for pattern in patterns):
            tags.append(label)
    if tags:
        tags.insert(0, "audit-correspondence")
    return unique_preserve_order(tags)


def significant_title_tokens(title: str) -> set[str]:
    tokens = normalize_title(title).split()
    return {token for token in tokens if len(token) >= 4 and token not in STOPWORDS}


def note_entry_type(metadata: dict[str, Any], collection_name: str) -> str:
    return infer_entry_type(metadata, collection_name)


def bibtex_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def build_bib_entry(
    key: str,
    metadata: dict[str, Any],
    pdf_path: Path,
    collection_name: str,
    omit_fields: set[str] | None = None,
) -> str:
    entry_type = metadata.get("entry_type") or note_entry_type(metadata, collection_name)
    omitted = omit_fields or set()
    fields: list[tuple[str, str]] = []
    authors = metadata.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    author_value = format_bibtex_author_list(authors)
    title = normalize_space(str(metadata.get("title") or pdf_path.stem.replace("_", " ")))
    year = normalize_space(str(metadata.get("year") or ""))
    venue = normalize_space(str(metadata.get("venue") or ""))
    publisher = normalize_space(str(metadata.get("publisher") or ""))
    volume = normalize_space(str(metadata.get("volume") or ""))
    issue = normalize_space(str(metadata.get("issue") or ""))
    pages = normalize_bib_pages(str(metadata.get("pages") or ""))
    note = normalize_space(str(metadata.get("note") or ""))
    url = meaningful_bib_url(metadata, entry_type)
    if author_value:
        fields.append(("author", author_value))
    fields.append(("title", title))
    if entry_type == "article" and venue:
        fields.append(("journal", venue))
    elif entry_type == "phdthesis":
        school = venue or publisher
        if school:
            fields.append(("school", school))
    elif entry_type == "incollection":
        if venue:
            fields.append(("booktitle", venue))
    elif entry_type == "book":
        pass
    elif entry_type == "techreport":
        institution = publisher or venue
        if institution:
            fields.append(("institution", institution))
    elif venue:
        fields.append(("howpublished", venue))
    elif publisher:
        fields.append(("howpublished", publisher))
    if year:
        fields.append(("year", year))
    if entry_type == "article":
        if volume:
            fields.append(("volume", volume))
        if issue:
            fields.append(("number", issue))
        if pages:
            fields.append(("pages", pages))
    elif entry_type == "incollection":
        if pages:
            fields.append(("pages", pages))
        if publisher:
            fields.append(("publisher", publisher))
    elif entry_type == "book":
        book_publisher = publisher or venue
        if book_publisher:
            fields.append(("publisher", book_publisher))
    if note and "note" not in omitted:
        fields.append(("note", note))
    if url and "url" not in omitted:
        fields.append(("url", url))
    if "file" not in omitted:
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
        venue = normalize_space(html.unescape(((message.get("container-title") or [""])[0])))
        doi = normalize_space(str(message.get("DOI") or "")).lower()
        abbr = infer_journal_abbr(venue, default_abbr)
        return {
            "title": normalize_space(html.unescape(((message.get("title") or [""])[0]))),
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
            "publisher": normalize_space(html.unescape(str(message.get("publisher") or ""))),
            "entry_type": entry_type_from_crossref(message, collection_name),
            "source": "crossref",
        }

    def metadata_from_openalex(self, item: dict[str, Any], default_abbr: str, collection_name: str) -> dict[str, Any]:
        doi = normalize_space(str(item.get("doi") or "")).replace("https://doi.org/", "").lower()
        venue = normalize_space(
            html.unescape((((item.get("primary_location") or {}).get("source") or {}).get("display_name") or ""))
        )
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
        metadata = {
            "title": normalize_space(html.unescape(str(item.get("display_name") or ""))),
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
            "source": "openalex",
        }
        metadata["entry_type"] = infer_entry_type(metadata, collection_name)
        return metadata

    def metadata_from_local_override(
        self,
        doi: str,
        override: dict[str, Any],
        extracted_abstract: str,
        fallback_url: str,
        collection_name: str,
    ) -> dict[str, Any]:
        venue = normalize_space(str(override.get("venue") or ""))
        canonical_doi = normalize_space(str(override.get("doi") or doi)).lower()
        metadata = {
            "title": normalize_space(str(override.get("title") or "")),
            "authors": [normalize_person_name(str(author)) for author in (override.get("authors") or []) if normalize_space(str(author))],
            "year": normalize_space(str(override.get("year") or "")),
            "venue": venue,
            "journal_abbr": canonical_journal_abbr(str(override.get("journal_abbr") or ""), venue),
            "doi": canonical_doi,
            "url": normalize_space(str(override.get("url") or fallback_url or (f"https://doi.org/{canonical_doi}" if canonical_doi else ""))),
            "abstract": extracted_abstract,
            "volume": normalize_space(str(override.get("volume") or "")),
            "issue": normalize_space(str(override.get("issue") or "")),
            "pages": normalize_space(str(override.get("pages") or "")),
            "publisher": normalize_space(str(override.get("publisher") or "")),
            "source": "local-override",
        }
        metadata["entry_type"] = infer_entry_type(metadata, collection_name)
        return metadata

    def normalize_note_metadata(self, data: dict[str, Any], collection_name: str) -> dict[str, Any]:
        authors = ensure_list(data.get("authors"))
        doi = normalize_space(str(data.get("doi") or "")).lower()
        venue = normalize_space(html.unescape(str(data.get("venue") or "")))
        abbr = infer_journal_abbr(venue, normalize_space(str(data.get("journal_abbr") or "")).lower())
        metadata = {
            "title": normalize_space(html.unescape(str(data.get("title") or ""))),
            "authors": cleaned_authors(authors),
            "year": str(data.get("year") or ""),
            "venue": venue,
            "journal_abbr": abbr,
            "doi": doi,
            "url": normalize_space(str(data.get("url") or (f"https://doi.org/{doi}" if doi else ""))),
            "abstract": "",
            "volume": "",
            "issue": "",
            "pages": "",
            "publisher": normalize_space(html.unescape(str(data.get("publisher") or ""))),
            "source": "note",
        }
        metadata["entry_type"] = infer_entry_type(metadata, collection_name)
        return metadata

    def resolve_metadata(self, pdf_path: Path, spec: CollectionSpec, note_data: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = parse_stem(pdf_path.stem)
        text = extract_pdf_text(pdf_path)
        pdf_title, pdf_author = title_from_pdf_metadata(pdf_path)
        extracted_abstract = extract_abstract_from_text(text)
        note_meta = self.normalize_note_metadata(note_data or {}, spec.category) if note_data else {}
        local_doi = extract_doi(pdf_title, text)
        preserve_wp_note_metadata = parsed["abbr"] == "wp" and bool(note_meta.get("title")) and bool(note_meta.get("authors"))
        override_doi = next(
            (
                doi
                for doi in unique_preserve_order(
                    [
                        normalize_space(str(note_meta.get("doi") or "")).lower(),
                        local_doi,
                    ]
                )
                if doi and doi in LOCAL_DOI_METADATA_OVERRIDES
            ),
            "",
        )
        local_override = LOCAL_DOI_METADATA_OVERRIDES.get(override_doi)
        if local_override:
            return self.metadata_from_local_override(
                override_doi,
                local_override,
                extracted_abstract,
                f"https://doi.org/{override_doi}" if override_doi else "",
                spec.category,
            )

        doi_candidates = unique_preserve_order(
            [
                normalize_space(str(note_meta.get("doi") or "")).lower(),
                local_doi,
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

        if preserve_wp_note_metadata:
            title = normalize_space(str(note_meta.get("title") or "")) or (
                pdf_title if is_plausible_title(pdf_title) else title_from_text(text)
            )
            if not title:
                title = normalize_space(pdf_path.stem.replace("_", " "))
            resolved_authors = cleaned_authors(note_meta.get("authors") or ([pdf_author] if normalize_space(pdf_author) else []))
            metadata = {
                "title": title,
                "authors": resolved_authors,
                "year": normalize_space(str(note_meta.get("year") or parsed["year"])),
                "venue": normalize_space(str(note_meta.get("venue") or self.abbr_map.get(parsed["abbr"], ""))),
                "journal_abbr": canonical_journal_abbr(str(note_meta.get("journal_abbr") or parsed["abbr"]), str(note_meta.get("venue") or "")),
                "doi": normalize_space(str(note_meta.get("doi") or "")),
                "url": normalize_space(str(note_meta.get("url") or "")),
                "abstract": extracted_abstract,
                "volume": "",
                "issue": "",
                "pages": "",
                "publisher": normalize_space(str(note_meta.get("publisher") or "")),
                "note": "Working paper metadata preserved from local note.",
                "source": "fallback",
            }
            metadata["entry_type"] = infer_entry_type(metadata, spec.category)
            return metadata

        title_candidates = unique_preserve_order(
            [
                normalize_space(str(note_meta.get("title") or "")),
                pdf_title if is_plausible_title(pdf_title) else "",
                title_from_text(text),
            ]
        )
        resolved_note_authors = cleaned_authors(note_meta.get("authors"))
        resolved_pdf_authors = cleaned_authors([pdf_author] if normalize_space(pdf_author) else [])
        author_token = ""
        if resolved_note_authors:
            author_token = first_author_slug(str(resolved_note_authors[0]))
        parsed_author = parsed["author"] if not is_placeholder_author(parsed["author"]) else ""
        author_token = author_token or parsed_author
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
        authors = resolved_note_authors or resolved_pdf_authors
        year = normalize_space(str(note_meta.get("year") or parsed["year"]))
        venue = normalize_space(str(note_meta.get("venue") or self.abbr_map.get(parsed["abbr"], "")))
        abbr = infer_journal_abbr(venue, note_meta.get("journal_abbr", "") or parsed["abbr"])
        if not title:
            title = normalize_space(pdf_path.stem.replace("_", " "))
        metadata = {
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venue,
            "journal_abbr": abbr,
            "doi": normalize_space(str(note_meta.get("doi") or "")),
            "url": normalize_space(str(note_meta.get("url") or "")),
            "abstract": extracted_abstract,
            "volume": "",
            "issue": "",
            "pages": "",
            "publisher": normalize_space(str(note_meta.get("publisher") or "")),
            "note": "Metadata inferred from local PDF; review recommended.",
            "source": "fallback",
        }
        metadata["entry_type"] = infer_entry_type(metadata, spec.category)
        return metadata


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
            venue = normalize_space(str(frontmatter.get("venue") or ""))
            abbr = canonical_journal_abbr(str(frontmatter.get("journal_abbr") or ""), venue)
            if abbr and venue:
                abbr_map.setdefault(abbr, venue)
    return abbr_map


def title_needs_replacement(title: str, stem: str) -> bool:
    normalized = normalize_space(title)
    if not normalized:
        return True
    if normalized.lower() == "untitled":
        return True
    if normalized.lower() in {"introduction", "preface", "editorial", "foreword"}:
        return True
    if "metadata unresolved" in normalized.lower():
        return True
    if normalize_title(normalized) == normalize_title(stem.replace("_", " ")):
        return True
    return False


def build_desired_stem(current_stem: str, metadata: dict[str, Any]) -> str:
    parsed = parse_stem(current_stem)
    authors = cleaned_authors(metadata.get("authors") or [])
    first_author = first_author_slug(str(authors[0])) if authors else ""
    parsed_author = parsed["author"] if not is_placeholder_author(parsed["author"]) else ""
    title_author = title_fallback_slug(str(metadata.get("title") or ""), current_stem)
    author = first_author or parsed_author or title_author
    year = normalize_space(str(metadata.get("year") or parsed["year"] or "undated"))
    abbr = classify_name_suffix(metadata, parsed["abbr"], str(metadata.get("category") or ""))
    abbr = slugify(abbr).replace("-", "_") if abbr else "misc"
    author = slugify(author).replace("-", "_")
    year = year if re.fullmatch(r"(19|20)\d{2}", year) else "undated"
    desired = f"{author}_{year}_{abbr}"
    if looks_standardized_stem(current_stem) and not parsed["copy_suffix"] and current_stem == desired:
        return current_stem
    return desired


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


def archive_identical_folder_duplicates(
    spec: CollectionSpec,
    note_paths: dict[str, Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[str]]]:
    hash_cache: dict[Path, str] = {}
    grouped: dict[tuple[int, str], list[Path]] = {}
    for pdf_path in sorted(spec.pdf_path.glob("*.pdf"), key=lambda path: path.name.lower()):
        digest = hash_file(pdf_path, hash_cache)
        grouped.setdefault((pdf_path.stat().st_size, digest), []).append(pdf_path)

    archive_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    alias_map: dict[str, list[str]] = {}

    for group in grouped.values():
        if len(group) < 2:
            continue
        ranked = sorted(
            group,
            key=lambda path: (
                0 if looks_standardized_stem(strip_copy_suffix(path.stem)) else 1,
                0 if note_paths.get(path.stem) and not note_is_stub(note_paths.get(path.stem)) else 1,
                0 if path.stem in note_paths else 1,
                len(path.name),
                path.name.lower(),
            ),
        )
        primary_path = ranked[0]
        primary_note = note_paths.get(primary_path.stem)
        for duplicate_path in ranked[1:]:
            duplicate_note = note_paths.get(duplicate_path.stem)
            if duplicate_note_safe(duplicate_note, primary_note):
                archived_path = archive_duplicate_pdf(duplicate_path, spec)
                archive_rows.append(
                    {
                        "collection": spec.pdf_dir,
                        "original_path": str(duplicate_path),
                        "archived_path": str(archived_path),
                        "primary_path": str(primary_path),
                        "reason": "exact_duplicate_in_folder",
                    }
                )
                alias_map.setdefault(primary_path.stem, []).append(duplicate_path.stem)
                continue
            review_rows.append(
                {
                    "collection": spec.pdf_dir,
                    "pdf_path": str(duplicate_path),
                    "conflict_path": str(primary_path),
                    "reason": "exact_duplicate_with_two_non_stub_notes",
                }
            )
    return archive_rows, review_rows, alias_map


def next_available_pdf_path(pdf_dir: Path, desired_stem: str, current_path: Path) -> Path:
    if current_path.stem == desired_stem:
        return current_path
    candidate = pdf_dir / f"{desired_stem}.pdf"
    if candidate == current_path:
        return current_path
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = pdf_dir / f"{desired_stem}_{index}.pdf"
        if candidate == current_path:
            return current_path
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


def collapse_orphaned_duplicate_notes(spec: CollectionSpec) -> int:
    pdf_stems = {pdf_path.stem for pdf_path in spec.pdf_path.glob("*.pdf")}
    note_paths = list_source_notes(spec.note_path)
    collapsed = 0
    for stem, note_path in sorted(note_paths.items()):
        if stem in pdf_stems:
            continue
        parsed = parse_stem(stem)
        if not parsed["copy_suffix"]:
            continue
        base_stem = strip_copy_suffix(stem)
        if base_stem not in pdf_stems:
            continue
        merge_note_files(spec.note_path / f"{base_stem}.md", note_path, base_stem, stem)
        collapsed += 1
    return collapsed


def matching_pdf_stems_for_orphan(stem: str, pdf_stems: set[str]) -> list[str]:
    parsed = parse_stem(stem)
    candidates: list[str] = []
    for candidate in sorted(pdf_stems):
        candidate_parsed = parse_stem(candidate)
        if parsed["author"] and candidate_parsed["author"] != parsed["author"]:
            continue
        if parsed["year"] and candidate_parsed["year"] != parsed["year"]:
            continue
        candidates.append(candidate)
    return candidates


def collapse_orphaned_renamed_notes(spec: CollectionSpec) -> int:
    pdf_stems = {pdf_path.stem for pdf_path in spec.pdf_path.glob("*.pdf")}
    note_paths = list_source_notes(spec.note_path)
    collapsed = 0
    for stem, note_path in sorted(note_paths.items()):
        if stem in pdf_stems:
            continue
        candidates = matching_pdf_stems_for_orphan(stem, pdf_stems)
        if len(candidates) != 1:
            continue
        target_stem = candidates[0]
        if target_stem == stem:
            continue
        frontmatter, _ = load_note(note_path)
        orphan_title = normalize_title(str(frontmatter.get("title") or ""))
        orphan_doi = normalize_space(str(frontmatter.get("doi") or "")).lower()
        target_path = spec.note_path / f"{target_stem}.md"
        title_match = False
        doi_match = False
        if target_path.exists():
            target_frontmatter, _ = load_note(target_path)
            target_title = normalize_title(str(target_frontmatter.get("title") or ""))
            target_doi = normalize_space(str(target_frontmatter.get("doi") or "")).lower()
            if orphan_doi and target_doi and orphan_doi == target_doi:
                doi_match = True
            if orphan_title and target_title and (
                orphan_title == target_title or SequenceMatcher(None, orphan_title, target_title).ratio() >= 0.92
            ):
                title_match = True
        else:
            title_match = bool(orphan_title)
        if not doi_match and not title_match:
            continue
        merge_note_files(target_path, note_path, target_stem, stem)
        collapsed += 1
    return collapsed


def note_title_is_generic_stub(title: str) -> bool:
    normalized = normalize_title(title)
    if not normalized:
        return True
    if normalized in {"nber working paper series", "working paper series"}:
        return True
    lowered = title.lower()
    if lowered.startswith("[renewcommand]") or "\\renewcommand" in lowered:
        return True
    letters = sum(ch.isalpha() for ch in title)
    digits = sum(ch.isdigit() for ch in title)
    upper = sum(ch.isupper() for ch in title if ch.isalpha())
    tokens = re.findall(r"[A-Za-z0-9]+", title)
    if digits and letters <= 12 and len(tokens) <= 3:
        return True
    if letters and upper / letters >= 0.7 and len(tokens) <= 3:
        return True
    return letters < 8


def prune_orphaned_imported_stub_notes(spec: CollectionSpec) -> int:
    pdf_stems = {pdf_path.stem for pdf_path in spec.pdf_path.glob("*.pdf")}
    note_paths = list_source_notes(spec.note_path)
    removed = 0
    for stem, note_path in sorted(note_paths.items()):
        if stem in pdf_stems:
            continue
        frontmatter, body = load_note(note_path)
        status = normalize_space(str(frontmatter.get("status") or "")).lower()
        if status != "imported-metadata":
            continue
        doi = normalize_space(str(frontmatter.get("doi") or "")).lower()
        year = normalize_space(str(frontmatter.get("year") or ""))
        venue = normalize_space(str(frontmatter.get("venue") or ""))
        title = normalize_space(str(frontmatter.get("title") or ""))
        if doi or venue or re.fullmatch(r"(19|20)\d{2}", year):
            continue
        if not note_title_is_generic_stub(title):
            continue
        if len(body.split()) > 500:
            continue
        note_path.unlink()
        removed += 1
    return removed


def redirect_legacy_notes(spec: CollectionSpec) -> int:
    redirects = LEGACY_NOTE_REDIRECTS.get(spec.category, {})
    redirected = 0
    for old_stem, new_stem in redirects.items():
        old_path = spec.note_path / f"{old_stem}.md"
        new_path = spec.note_path / f"{new_stem}.md"
        if not old_path.exists():
            continue
        old_frontmatter, _ = load_note(old_path)
        old_aliases = [str(alias) for alias in ensure_list(old_frontmatter.get("aliases"))]
        if not new_path.exists():
            old_path.rename(new_path)
            new_frontmatter, new_body = load_note(new_path)
            ensure_aliases(new_frontmatter, old_stem, new_stem, *old_aliases)
            new_path.write_text(dump_frontmatter(new_frontmatter) + new_body.rstrip() + "\n")
            redirected += 1
            continue
        new_frontmatter, new_body = load_note(new_path)
        ensure_aliases(new_frontmatter, old_stem, new_stem, *old_aliases)
        new_path.write_text(dump_frontmatter(new_frontmatter) + new_body.rstrip() + "\n")
        old_path.unlink()
        redirected += 1
    return redirected


def repair_pdf_links(text: str, folder_map: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        folder = match.group(1)
        filename = match.group(2)
        alias = match.group(3) or ""
        canonical = folder_map.get(folder, folder)
        return f"[[{canonical}/{filename}{alias}]]"

    return re.sub(r"\[\[([^/\]|]+)/([^|\]]+\.pdf)(\|[^\]]+)?\]\]", repl, text)


def repair_note_links(text: str, note_index: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        parts = inner.split("|", 1)
        target = parts[0]
        if target.endswith(".pdf") or target.startswith("http"):
            return match.group(0)
        fixed = canonicalize_note_target(target, note_index)
        if not fixed or fixed == target or fixed == target.removesuffix(".md"):
            return match.group(0)
        if len(parts) == 2:
            return f"[[{fixed}|{parts[1]}]]"
        return f"[[{fixed}]]"

    return re.sub(r"\[\[([^\]]+)\]\]", repl, text)


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


def significant_text_tokens(text: str, limit: int = 24) -> set[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for token in normalize_title(text).split():
        if len(token) < 4 or token in STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
        if len(ordered) >= limit:
            break
    return set(ordered)


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
    existing_tags = {normalize_space(str(tag)) for tag in ensure_list(frontmatter.get("tags")) if normalize_space(str(tag))}
    status = normalize_space(str(frontmatter.get("status") or "")).lower()
    prefer_metadata = status == "imported-metadata" or "metadata-review" in existing_tags
    title = normalize_space(str(data.get("title") or ""))
    resolved_title = normalize_space(str(metadata.get("title") or ""))
    if title_needs_replacement(title, stem) and resolved_title:
        title = resolved_title
    data["type"] = "source-note"
    data["title"] = title or resolved_title or stem.replace("_", " ")
    ensure_aliases(data, stem)
    authors = cleaned_authors(data.get("authors"))
    metadata_authors = cleaned_authors(metadata.get("authors") or [])
    if prefer_metadata and metadata_authors:
        authors = metadata_authors
    elif not authors:
        authors = metadata_authors
    data["authors"] = authors
    data["year"] = coerce_year((metadata.get("year") if prefer_metadata else data.get("year")) or data.get("year") or metadata.get("year") or "")
    venue = normalize_space(str((metadata.get("venue") if prefer_metadata else data.get("venue")) or data.get("venue") or metadata.get("venue") or ""))
    data["venue"] = venue
    data["publisher"] = normalize_space(
        str((metadata.get("publisher") if prefer_metadata else data.get("publisher")) or data.get("publisher") or metadata.get("publisher") or "")
    )
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
    source_fields = {**data, **metadata} if prefer_metadata else {**metadata, **data}
    fallback_source_abbr = (
        str(metadata.get("journal_abbr") or data.get("journal_abbr") or "")
        if prefer_metadata
        else str(data.get("journal_abbr") or metadata.get("journal_abbr") or "")
    )
    data["entry_type"] = infer_entry_type(source_fields, spec.category)
    data["journal_abbr"] = source_tag_slug(source_fields, fallback_source_abbr, spec.category)
    data["cases"] = ensure_list(data.get("cases"))
    data["projects"] = ensure_list(data.get("projects"))
    data["status"] = data.get("status") or "imported-metadata"
    data["priority"] = data.get("priority") or "medium"
    data["rating"] = data.get("rating", None)
    data["pdf_local"] = f"[[{spec.pdf_dir}/{pdf_name}]]"
    doi = normalize_space(
        str((metadata.get("doi") if prefer_metadata else data.get("doi")) or data.get("doi") or metadata.get("doi") or "")
    ).lower()
    data["doi"] = doi
    data["url"] = normalize_space(
        str((metadata.get("url") if prefer_metadata else data.get("url")) or data.get("url") or metadata.get("url") or (f"https://doi.org/{doi}" if doi else ""))
    )
    data["zotero_key"] = normalize_space(str(data.get("zotero_key") or ""))
    data["date_added"] = data.get("date_added") or TODAY
    data["last_reviewed"] = TODAY
    removable_source_tags = (
        set(KNOWN_JOURNALS)
        | set(JOURNAL_ABBR_ALIASES)
        | {
            "misc",
            "book",
            "wp",
            "wpol",
            "article",
            normalize_space(str(frontmatter.get("journal_abbr") or "")).lower(),
            normalize_space(str(metadata.get("journal_abbr") or "")).lower(),
            fallback_journal_slug(venue),
        }
    )
    tags = [
        normalize_space(str(tag))
        for tag in ensure_list(data.get("tags"))
        if normalize_space(str(tag)) and normalize_space(str(tag)) not in removable_source_tags
    ]
    tags.extend(["literature", "source-note", slugify(spec.category).replace("_", "-")])
    if data["journal_abbr"]:
        tags.append(str(data["journal_abbr"]))
    if note_entry_type(data, spec.category) == "article":
        tags.append("article")
    tags.extend(
        infer_audit_tags(
            data["title"],
            str(metadata.get("abstract") or ""),
            " ".join(data["methods"]),
            " ".join(str(item) for item in ensure_list(data.get("keywords"))),
            " ".join(str(item) for item in ensure_list(data.get("topics"))),
        )
    )
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
        body = upsert_section(body, "Basic Information", build_basic_information_lines(merged, spec, pdf_path.name))
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
        build_basic_information_lines(frontmatter, spec, pdf_path.name),
        "",
        "## Abstract / Extracted Summary",
        abstract,
        "",
        "## Notes",
        "- ",
        "",
    ]
    return dump_frontmatter(frontmatter) + "\n".join(body_parts)


def note_metadata_for_relations(note_path: Path, spec: CollectionSpec) -> dict[str, Any]:
    frontmatter, body = load_note(note_path)
    raw_tags = [normalize_space(str(tag)) for tag in ensure_list(frontmatter.get("tags")) if normalize_space(str(tag))]
    common_tags = {
        "literature",
        "source-note",
        "article",
        "needs-summary",
        "metadata-review",
        slugify(spec.category).replace("_", "-"),
    }
    tags: list[str] = []
    for tag in raw_tags:
        if tag in common_tags:
            continue
        if tag.startswith("theme/"):
            tags.append(tag.split("/", 1)[1].replace("_", " "))
            continue
        tags.append(tag.replace("_", " "))
    summary_chunks = [
        get_section(body, "Abstract / Extracted Summary"),
        get_section(body, "Summary"),
        get_section(body, "One-Sentence Takeaway"),
        get_section(body, "Core Argument"),
        get_section(body, "Research Question"),
        get_section(body, "Source Excerpt"),
    ]
    return {
        "stem": note_path.stem,
        "note_dir": spec.note_dir,
        "category": spec.category,
        "title": normalize_space(str(frontmatter.get("title") or "")),
        "authors": [normalize_space(str(author)) for author in ensure_list(frontmatter.get("authors")) if normalize_space(str(author))],
        "keywords": [normalize_space(str(keyword)) for keyword in ensure_list(frontmatter.get("keywords")) if normalize_space(str(keyword))],
        "topics": [normalize_space(str(topic)) for topic in ensure_list(frontmatter.get("topics")) if normalize_space(str(topic))],
        "methods": [normalize_space(str(method)) for method in ensure_list(frontmatter.get("methods")) if normalize_space(str(method))],
        "regions": [normalize_space(str(region)) for region in ensure_list(frontmatter.get("regions")) if normalize_space(str(region))],
        "tags": tags,
        "summary": normalize_space(" ".join(chunk for chunk in summary_chunks if chunk)),
        "venue": normalize_space(str(frontmatter.get("venue") or "")),
        "year": normalize_space(str(frontmatter.get("year") or "")),
        "journal_abbr": normalize_space(str(frontmatter.get("journal_abbr") or "")).lower(),
    }


def relation_signature(item: dict[str, Any]) -> dict[str, Any]:
    author_keys = {first_author_slug(author) for author in item["authors"] if first_author_slug(author)}
    keyword_tokens = set()
    for field in item["keywords"] + item["topics"] + item["tags"]:
        keyword_tokens.update(token for token in slugify(field).split("_") if len(token) >= 4 and token not in STOPWORDS)
    keyword_tokens |= significant_title_tokens(item["title"])
    keyword_tokens |= significant_text_tokens(item["summary"], limit=18)
    return {
        "authors": author_keys,
        "regions": {slugify(region) for region in item["regions"]},
        "methods": {slugify(method) for method in item["methods"]},
        "tokens": keyword_tokens,
        "journal_abbr": item["journal_abbr"],
        "collection": slugify(item["note_dir"]),
        "year": item["year"],
    }


def relation_score(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, list[str], bool]:
    sig_a = relation_signature(a)
    sig_b = relation_signature(b)
    reasons: list[str] = []
    score = 0.0
    strong_signal = False
    shared_authors = sig_a["authors"] & sig_b["authors"]
    if shared_authors:
        score += 1.8
        reasons.append("shared author")
        strong_signal = True
    shared_regions = sig_a["regions"] & sig_b["regions"]
    if shared_regions:
        score += 1.0
        reasons.extend(sorted(shared_regions)[:2])
        strong_signal = True
    shared_methods = sig_a["methods"] & sig_b["methods"]
    if shared_methods:
        score += 0.8
        reasons.extend(sorted(shared_methods)[:2])
        strong_signal = True
    shared_tokens = sorted((sig_a["tokens"] & sig_b["tokens"]) - STOPWORDS)
    if shared_tokens:
        score += min(1.8, 0.22 * len(shared_tokens))
        reasons.extend(shared_tokens[:3])
        if len(shared_tokens) >= 2:
            strong_signal = True
    if sig_a["journal_abbr"] and sig_a["journal_abbr"] == sig_b["journal_abbr"]:
        score += 0.2
    if sig_a["collection"] == sig_b["collection"]:
        score += 0.22
    year_a = sig_a["year"]
    year_b = sig_b["year"]
    if year_a.isdigit() and year_b.isdigit() and abs(int(year_a) - int(year_b)) <= 3:
        score += 0.08
    return score, unique_preserve_order(reasons), strong_signal


def extract_related_bullets(body: str) -> list[str]:
    bullets: list[str] = []
    for heading in ["Related Papers", "Related Dissertations", "Related Articles", "Related Notes"]:
        section = get_section(body, heading)
        if not section:
            continue
        for line in section.splitlines():
            stripped = line.strip()
            if stripped.startswith("- [["):
                bullets.append(stripped)
    return bullets


def related_bullet_key(line: str) -> str:
    match = re.search(r"\[\[([^\]|]+)", line)
    return match.group(1) if match else line


def merge_related_bullets(existing: list[str], generated: list[str], limit: int = 8) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for bullet in existing + generated:
        key = related_bullet_key(bullet)
        if key in seen:
            continue
        seen.add(key)
        merged.append(bullet)
        if len(merged) >= limit:
            break
    return "\n".join(merged) if merged else "- "


def note_link(item: dict[str, Any]) -> str:
    return f"[[{NOTES_FOLDER_NAME}/{item['note_dir']}/{item['stem']}|{item['title']}]]"


def repair_all_note_links(collections: list[CollectionSpec]) -> int:
    note_index = build_note_index(collections)
    updates = 0
    for spec in collections:
        for note_path in list_source_notes(spec.note_path).values():
            original = note_path.read_text(errors="ignore")
            rebuilt = repair_note_links(original, note_index)
            if rebuilt != original:
                note_path.write_text(rebuilt)
                updates += 1
    return updates


def update_related_sections(collections: list[CollectionSpec]) -> int:
    note_paths: dict[str, Path] = {}
    note_items: dict[str, dict[str, Any]] = {}
    for spec in collections:
        for stem, path in list_source_notes(spec.note_path).items():
            note_id = f"{spec.note_dir}/{stem}"
            note_paths[note_id] = path
            note_items[note_id] = note_metadata_for_relations(path, spec)

    updates = 0
    for note_id, item in note_items.items():
        candidates: list[tuple[float, int, str, list[str]]] = []
        fallback: list[tuple[float, int, str, list[str]]] = []
        for other_id, other_item in note_items.items():
            if other_id == note_id:
                continue
            score, reasons, strong_signal = relation_score(item, other_item)
            same_collection_rank = 0 if item["note_dir"] == other_item["note_dir"] else 1
            if score >= 1.0 or (strong_signal and score >= 0.58) or (same_collection_rank == 0 and score >= 0.48):
                candidates.append((score, same_collection_rank, other_id, reasons))
            elif score >= 0.35 and (strong_signal or same_collection_rank == 0 or len(reasons) >= 2):
                fallback.append((score, same_collection_rank, other_id, reasons))
        ranked = candidates or fallback
        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        generated: list[str] = []
        for _, _, other_id, reasons in ranked[:6]:
            other_item = note_items[other_id]
            reason_text = ", ".join(reason.replace("_", " ") for reason in reasons[:3])
            if reason_text:
                generated.append(f"- {note_link(other_item)}  | shared: {reason_text}")
            else:
                generated.append(f"- {note_link(other_item)}")
        note_path = note_paths[note_id]
        original = note_path.read_text(errors="ignore")
        frontmatter, body = parse_frontmatter(original)
        existing = extract_related_bullets(body)
        updated_body = upsert_section(body, "Related Literature", merge_related_bullets(existing, generated))
        rebuilt = dump_frontmatter(frontmatter) + updated_body.rstrip() + "\n"
        if rebuilt != original:
            note_path.write_text(rebuilt)
            updates += 1
    return updates


def write_folder_info(spec: CollectionSpec, pdf_count: int, note_count: int, review_count: int) -> None:
    folder_info_path = spec.pdf_path / "_folder_info.md"
    if folder_info_path.exists():
        folder_info_path.unlink()


def clean_collection_non_pdf_files(spec: CollectionSpec) -> int:
    removed = 0
    for path in spec.pdf_path.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() == ".pdf":
            continue
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def bibliography_entries_for_spec(
    spec: CollectionSpec,
    omit_fields: set[str] | None = None,
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
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
                "publisher": frontmatter.get("publisher") or "",
                "entry_type": frontmatter.get("entry_type") or note_entry_type(frontmatter, spec.category),
                "volume": frontmatter.get("volume") or "",
                "issue": frontmatter.get("issue") or "",
                "pages": frontmatter.get("pages") or "",
                "note": frontmatter.get("note") or "",
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
                "publisher": "",
                "volume": "",
                "issue": "",
                "pages": "",
                "note": "",
                "entry_type": note_entry_type({}, spec.category),
            }
        entries.append(
            (
                pdf_path.stem,
                build_bib_entry(
                    pdf_path.stem,
                    metadata,
                    pdf_path,
                    spec.category,
                    omit_fields=omit_fields,
                ),
            )
        )
    return entries


def write_bibliography(collections: list[CollectionSpec]) -> Path:
    deduped_entries: dict[str, str] = {}
    for spec in collections:
        for key, entry in bibliography_entries_for_spec(spec, omit_fields=BIB_OMIT_FIELDS):
            deduped_entries[key] = entry
    GLOBAL_BIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered_entries = [deduped_entries[key] for key in sorted(deduped_entries)]
    GLOBAL_BIB_PATH.write_text("\n\n".join(ordered_entries) + "\n", encoding="utf-8")
    return GLOBAL_BIB_PATH


def remove_legacy_bibliographies() -> int:
    removed = 0
    if not REFERENCE_ROOT.exists():
        return removed
    for bib_path in REFERENCE_ROOT.glob("*.bib"):
        if bib_path == GLOBAL_BIB_PATH:
            continue
        bib_path.unlink(missing_ok=True)
        removed += 1
    return removed


def pending_journal_source_rows(collections: list[CollectionSpec]) -> list[dict[str, Any]]:
    by_slug: dict[str, dict[str, Any]] = {}
    for spec in collections:
        for note_path in list_source_notes(spec.note_path).values():
            frontmatter, _ = load_note(note_path)
            venue = normalize_space(html.unescape(str(frontmatter.get("venue") or "")))
            if not venue:
                continue
            entry_type = infer_entry_type(frontmatter, spec.category)
            if entry_type != "article":
                continue
            slug = fallback_journal_slug(venue)
            if not slug or slug in KNOWN_JOURNALS:
                continue
            source_tag = source_tag_slug(frontmatter, str(frontmatter.get("journal_abbr") or ""), spec.category)
            if source_tag in KNOWN_JOURNALS:
                continue
            title_aliases = []
            if venue.lower().startswith("the "):
                title_aliases.append(venue[4:])
            row = by_slug.setdefault(
                slug,
                {
                    "code": suggested_source_code(venue),
                    "display_name": venue,
                    "openalex_source_id": "",
                    "filename_slug": slug,
                    "publisher": normalize_space(str(frontmatter.get("publisher") or "")),
                    "publisher_domains": "",
                    "title_aliases": "; ".join(title_aliases),
                    "collections": set(),
                    "note_count": 0,
                    "sample_note": str(note_path),
                    "updated": TODAY,
                },
            )
            row["collections"].add(spec.category)
            row["note_count"] += 1
            if not row["publisher"]:
                row["publisher"] = normalize_space(str(frontmatter.get("publisher") or ""))

    rows: list[dict[str, Any]] = []
    for slug, row in sorted(by_slug.items(), key=lambda item: item[0]):
        rows.append(
            {
                "code": row["code"],
                "display_name": row["display_name"],
                "openalex_source_id": row["openalex_source_id"],
                "filename_slug": row["filename_slug"],
                "publisher": row["publisher"],
                "publisher_domains": row["publisher_domains"],
                "title_aliases": row["title_aliases"],
                "collections": "; ".join(sorted(row["collections"])),
                "note_count": str(row["note_count"]),
                "sample_note": row["sample_note"],
                "updated": row["updated"],
            }
        )
    return rows


def write_pending_journal_sources(collections: list[CollectionSpec]) -> Path:
    rows = pending_journal_source_rows(collections)
    write_csv(
        PENDING_JOURNAL_SOURCES_PATH,
        rows,
        [
            "code",
            "display_name",
            "openalex_source_id",
            "filename_slug",
            "publisher",
            "publisher_domains",
            "title_aliases",
            "collections",
            "note_count",
            "sample_note",
            "updated",
        ],
    )
    return PENDING_JOURNAL_SOURCES_PATH


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
    pre_archive_rows, pre_review_rows, alias_map = archive_identical_folder_duplicates(spec, note_paths)
    note_paths = list_source_notes(spec.note_path)
    hash_cache: dict[Path, str] = {}
    rename_rows: list[dict[str, Any]] = []
    archive_rows: list[dict[str, Any]] = list(pre_archive_rows)
    review_rows: list[dict[str, Any]] = list(pre_review_rows)

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
        note_title = normalize_space(str((note_data or {}).get("title") or ""))
        should_resolve = (
            not looks_standardized_stem(strip_copy_suffix(pdf_path.stem))
            or bool(parse_stem(pdf_path.stem)["copy_suffix"])
            or note_path is None
            or note_is_stub(note_path)
            or title_needs_replacement(note_title, pdf_path.stem)
        )
        if should_resolve:
            metadata = resolver.resolve_metadata(pdf_path, spec, note_data)
        else:
            metadata = resolver.normalize_note_metadata(note_data or {}, spec.category)
        metadata["category"] = spec.category
        current_stem = pdf_path.stem

        # Avoid renaming already-standardized files when metadata only comes
        # from local fallback heuristics, which is common during offline runs.
        if looks_standardized_stem(strip_copy_suffix(current_stem)) and metadata.get("source") == "fallback":
            continue

        desired_stem = build_desired_stem(pdf_path.stem, metadata)
        desired_path = spec.pdf_path / f"{desired_stem}.pdf"

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
    redirect_legacy_notes(spec)

    note_paths = list_source_notes(spec.note_path)
    for new_stem, aliases in alias_map.items():
        for old_stem in aliases:
            old_note = spec.note_path / f"{old_stem}.md"
            new_note = spec.note_path / f"{new_stem}.md"
            if old_note.exists() and old_note != new_note:
                merge_note_files(new_note, old_note, new_stem, old_stem)

    collapse_orphaned_duplicate_notes(spec)
    collapse_orphaned_renamed_notes(spec)
    prune_orphaned_imported_stub_notes(spec)
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

    note_paths = list_source_notes(spec.note_path)
    metadata_review_count = 0
    for note_path in note_paths.values():
        frontmatter, _ = load_note(note_path)
        tags = set(str(tag) for tag in ensure_list(frontmatter.get("tags")))
        if "metadata-review" in tags:
            metadata_review_count += 1

    write_folder_info(spec, len(list(spec.pdf_path.glob("*.pdf"))), len(note_paths), metadata_review_count)
    removed_non_pdf_files = clean_collection_non_pdf_files(spec)

    return {
        "collection": spec.pdf_dir,
        "category": spec.category,
        "pdf_count": len(list(spec.pdf_path.glob("*.pdf"))),
        "note_count": len(note_paths),
        "created_notes": created_notes,
        "updated_notes": updated_notes,
        "related_updates": 0,
        "metadata_review_count": metadata_review_count,
        "rename_rows": rename_rows,
        "archive_rows": archive_rows,
        "review_rows": review_rows,
        "removed_non_pdf_files": removed_non_pdf_files,
        "bib_path": str(GLOBAL_BIB_PATH),
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
    all_collections = discover_collections()
    collections = discover_collections(filters)
    folder_map = build_pdf_folder_map(collections)
    abbr_map = build_abbr_map(all_collections)
    resolver = MetadataResolver(abbr_map)

    summaries: list[dict[str, Any]] = []
    rename_rows: list[dict[str, Any]] = []
    archive_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    removed_non_pdf_files = 0

    for spec in collections:
        summary = sync_collection(spec, resolver, folder_map)
        summaries.append(summary)
        rename_rows.extend(summary["rename_rows"])
        archive_rows.extend(summary["archive_rows"])
        review_rows.extend(summary["review_rows"])
        removed_non_pdf_files += summary["removed_non_pdf_files"]
        print(
            f"{spec.pdf_dir}: pdfs={summary['pdf_count']}, notes={summary['note_count']}, "
            f"created={summary['created_notes']}, updated={summary['updated_notes']}, "
            f"review={summary['metadata_review_count']}"
        )

    bibliography_path = write_bibliography(all_collections)
    removed_legacy_bibs = remove_legacy_bibliographies()
    repaired_note_links = repair_all_note_links(collections)
    related_updates = update_related_sections(collections)
    pending_sources_path = write_pending_journal_sources(collections)

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
    print(f"Unified bibliography: {bibliography_path}")
    print(f"Legacy bibliographies removed: {removed_legacy_bibs}")
    print(f"Renamed PDFs: {len(rename_rows)}")
    print(f"Archived duplicate PDFs: {len(archive_rows)}")
    print(f"Duplicate review items: {len(review_rows)}")
    print(f"Removed non-PDF collection files: {removed_non_pdf_files}")
    print(f"Repaired note links: {repaired_note_links}")
    print(f"Updated related sections: {related_updates}")
    print(f"Pending journal source queue: {pending_sources_path}")


if __name__ == "__main__":
    main()
