from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
LIBRARY_DIR = BASE_DIR / "library"
DEFAULT_OUTPUT = LIBRARY_DIR / "zotero_digest.json"
LIVE_EXPORT_PATH = LIBRARY_DIR / "zotero_live_export.bib"
PLUGIN_STATUS_PATH = LIBRARY_DIR / "zotero_plugin_status.json"
COLLECTIONS_PATH = LIBRARY_DIR / "zotero_collections.json"


PROJECT_TERMS = [
    "antibubble",
    "\u53cd\u6c14\u6ce1",
    "plateau border",
    "plateau",
    "pb",
    "foam",
    "\u6ce1\u6cab",
    "liquid film",
    "air film",
    "\u6db2\u819c",
    "\u6c14\u819c",
    "droplet",
    "drop",
    "\u6db2\u6ef4",
    "particle",
    "sphere",
    "solid",
    "rigid",
    "\u9897\u7c92",
    "\u5c0f\u7403",
    "interface",
    "\u754c\u9762",
    "transport",
    "\u8f93\u8fd0",
    "scaling",
    "criteria",
    "\u5224\u636e",
    "\u65e0\u91cf\u7eb2",
]


TOPIC_RULES = {
    "antibubble_core": [
        "antibubble",
        "\u53cd\u6c14\u6ce1",
    ],
    "plateau_border_foam": [
        "plateau border",
        "plateau",
        "foam",
        "pb",
        "\u6ce1\u6cab",
    ],
    "droplet_impact_transport": [
        "drop impact",
        "droplet",
        "drop",
        "coalescence",
        "imbibition",
        "liquid flow",
        "transport",
        "\u6db2\u6ef4",
        "\u8f93\u8fd0",
    ],
    "rigid_particles_interfaces": [
        "particle",
        "particles",
        "sphere",
        "solid particle",
        "rigid",
        "settling",
        "particulate projectile",
        "interface",
        "\u9897\u7c92",
        "\u5c0f\u7403",
        "\u521a\u4f53",
    ],
    "liquid_film_measurement": [
        "film",
        "air film",
        "liquid film",
        "thickness",
        "drainage",
        "\u6c14\u819c",
        "\u6db2\u819c",
        "\u6d4b\u91cf",
    ],
    "ultrasound_acoustic": [
        "ultrasound",
        "acoustic",
        "cavitation",
        "sonoporation",
        "\u8d85\u58f0",
        "\u7a7a\u5316",
    ],
    "encapsulation_pickering": [
        "pickering",
        "encapsulation",
        "drug delivery",
        "payload",
        "emulsion",
        "\u5c01\u88c5",
    ],
    "phase_criteria_scaling": [
        "scaling",
        "criteria",
        "criterion",
        "dimensionless",
        "reynolds",
        "weber",
        "capillary",
        "bond",
        "\u76f8\u56fe",
        "\u5224\u636e",
        "\u65e0\u91cf\u7eb2",
    ],
    "vortex_jet_impact": [
        "vortex",
        "jet",
        "water entry",
        "projectile",
        "impact",
        "\u6da1\u73af",
    ],
}


def _compact_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_bib_value(value: str) -> str:
    value = value.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_")
    value = value.replace("\\textendash", "-").replace("\\textemdash", "-")
    value = value.replace("{", "").replace("}", "")
    return _compact_space(value)


def normalize_doi(value: str) -> str:
    value = clean_bib_value(value).strip()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", value, flags=re.I)
    if not match:
        return ""
    return match.group(0).rstrip(".,;").lower()


def normalize_title_key(value: str) -> str:
    value = clean_bib_value(value).lower()
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", value)
    return _compact_space(value)


def safe_path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def find_bibtex_files(library_dir: Path) -> list[Path]:
    live_export = library_dir / "zotero_live_export.bib"
    if live_export.is_file():
        return [live_export]
    candidates = [
        library_dir / "zotero_library.bib" / "zotero_library.bib.bib",
        library_dir / "zotero_library.bib",
    ]
    discovered = sorted(library_dir.glob("*.bib")) + sorted(library_dir.glob("**/*.bib"))
    seen: set[Path] = set()
    files: list[Path] = []
    for path in [*candidates, *discovered]:
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        files.append(path)
    return files


def _find_matching_entry_end(text: str, opener_index: int, opener: str) -> int:
    closer = "}" if opener == "{" else ")"
    depth = 1
    index = opener_index + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return len(text) - 1


def iter_bibtex_entries(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    index = 0
    while True:
        at = text.find("@", index)
        if at == -1:
            break
        match = re.match(r"@([A-Za-z]+)\s*([\{\(])", text[at:])
        if not match:
            index = at + 1
            continue
        entry_type = match.group(1).lower()
        opener = match.group(2)
        opener_index = at + match.end() - 1
        end = _find_matching_entry_end(text, opener_index, opener)
        content = text[opener_index + 1 : end]
        comma = content.find(",")
        if comma == -1:
            index = end + 1
            continue
        key = content[:comma].strip()
        fields = parse_bibtex_fields(content[comma + 1 :])
        entries.append({"entry_type": entry_type, "key": key, "fields": fields})
        index = end + 1
    return entries


def _parse_braced_value(text: str, index: int) -> tuple[str, int]:
    depth = 1
    start = index + 1
    index += 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index], index + 1
        index += 1
    return text[start:], len(text)


def _parse_quoted_value(text: str, index: int) -> tuple[str, int]:
    depth = 0
    start = index + 1
    index += 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == '"' and depth == 0:
            return text[start:index], index + 1
        index += 1
    return text[start:], len(text)


def _parse_unquoted_value(text: str, index: int) -> tuple[str, int]:
    start = index
    while index < len(text) and text[index] not in ",\n\r":
        index += 1
    return text[start:index], index


def parse_bibtex_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    index = 0
    while index < len(text):
        while index < len(text) and text[index] in " \t\r\n,":
            index += 1
        name_match = re.match(r"([A-Za-z][A-Za-z0-9_-]*)\s*=", text[index:])
        if not name_match:
            index += 1
            continue
        name = name_match.group(1).lower()
        index += name_match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            fields[name] = ""
            break
        if text[index] == "{":
            value, index = _parse_braced_value(text, index)
        elif text[index] == '"':
            value, index = _parse_quoted_value(text, index)
        else:
            value, index = _parse_unquoted_value(text, index)
        fields[name] = clean_bib_value(value)
        while index < len(text) and text[index] != ",":
            if not text[index].isspace():
                break
            index += 1
        if index < len(text) and text[index] == ",":
            index += 1
    return fields


def split_keywords(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,;]\s*", value)
    return [part.strip() for part in parts if part.strip()]


def read_status_from_keywords(keywords: list[str]) -> str:
    lowered = [item.lower() for item in keywords]
    has_read = any(
        item in {"read", "/read"} or item.endswith("/read") or "\u5df2\u8bfb" in item
        for item in lowered
    )
    has_unread = any("unread" in item or "\u672a\u8bfb" in item for item in lowered)
    if has_read and has_unread:
        return "mixed"
    if has_read:
        return "read"
    if has_unread:
        return "unread"
    return "unknown"


def parse_year(fields: dict[str, str]) -> int | None:
    for key in ("year", "date"):
        value = fields.get(key, "")
        match = re.search(r"\b(19\d{2}|20\d{2})\b", value)
        if match:
            return int(match.group(1))
    return None


def parse_attachments(file_field: str, bib_dir: Path) -> list[dict[str, Any]]:
    attachments = []
    if not file_field:
        return attachments
    for chunk in file_field.split(";"):
        try:
            name_and_path, mime = chunk.rsplit(":", 1)
        except ValueError:
            continue
        if ":" in name_and_path:
            name, raw_path = name_and_path.split(":", 1)
        else:
            name, raw_path = Path(name_and_path).name, name_and_path
        cleaned_path = raw_path.replace("\\:", ":").replace("\\\\", "\\").strip()
        candidate = Path(cleaned_path)
        path = candidate if candidate.is_absolute() else (bib_dir / cleaned_path)
        path = path.resolve(strict=False)
        attachments.append(
            {
                "name": name.strip() or Path(cleaned_path).name,
                "kind": mime or Path(cleaned_path).suffix.lower().lstrip("."),
                "relative_path": cleaned_path.replace("\\", "/"),
                "path": str(path),
                "exists": safe_path_exists(path),
            }
        )
    return attachments


def classify_topics(entry: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(entry.get(key, ""))
        for key in ("title", "abstract", "keywords_text", "journal", "shorttitle")
    ).lower()
    topics = []
    for topic, terms in TOPIC_RULES.items():
        if any(term.lower() in text for term in terms):
            topics.append(topic)
    return topics or ["general_reference"]


def project_relevance_score(entry: dict[str, Any]) -> float:
    text = " ".join(
        str(entry.get(key, ""))
        for key in ("title", "abstract", "keywords_text", "journal", "shorttitle")
    ).lower()
    score = 0.0
    for term in PROJECT_TERMS:
        if term.lower() in text:
            score += 3.0
    year = entry.get("year")
    if isinstance(year, int):
        if year >= 2024:
            score += 12.0
        elif year >= 2020:
            score += 8.0
        elif year >= 2015:
            score += 3.0
        elif year < 2000:
            score -= 5.0
    if "review" in text or "\u7efc\u8ff0" in text:
        score += 8.0
    if entry.get("doi"):
        score += 2.0
    if entry.get("abstract"):
        score += 3.0
    if any(item.get("exists") and str(item.get("kind", "")).lower().endswith("pdf") for item in entry.get("attachments", [])):
        score += 3.0
    if entry.get("read_status") == "read":
        score += 2.0
    return round(max(0.0, min(score, 100.0)), 1)


def compact_entry(raw: dict[str, Any], bib_dir: Path, source_file: Path) -> dict[str, Any]:
    fields = raw["fields"]
    keywords = split_keywords(fields.get("keywords", ""))
    attachments = parse_attachments(fields.get("file", ""), bib_dir)
    entry = {
        "key": raw["key"],
        "entry_type": raw["entry_type"],
        "title": fields.get("title", ""),
        "shorttitle": fields.get("shorttitle", ""),
        "year": parse_year(fields),
        "doi": normalize_doi(fields.get("doi", "")),
        "url": fields.get("url", ""),
        "journal": fields.get("journal", fields.get("journaltitle", "")),
        "author": fields.get("author", ""),
        "abstract": fields.get("abstract", ""),
        "keywords": keywords,
        "keywords_text": fields.get("keywords", ""),
        "read_status": read_status_from_keywords(keywords),
        "attachments": attachments,
        "source_bib": str(source_file),
    }
    entry["topics"] = classify_topics(entry)
    entry["project_relevance"] = project_relevance_score(entry)
    entry["has_pdf"] = any(item.get("exists") and "pdf" in str(item.get("kind", "")).lower() for item in attachments)
    entry["has_abstract"] = bool(entry["abstract"])
    return entry


def dedupe_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        key = f"doi:{entry['doi']}" if entry.get("doi") else f"title:{normalize_title_key(entry.get('title', ''))}"
        groups[key].append(entry)
    unique = []
    duplicates = []
    for key, group in groups.items():
        group.sort(
            key=lambda item: (
                item.get("project_relevance") or 0,
                bool(item.get("has_pdf")),
                bool(item.get("has_abstract")),
                item.get("year") or 0,
            ),
            reverse=True,
        )
        unique.append(group[0])
        if len(group) > 1:
            duplicates.append(
                {
                    "key": key,
                    "count": len(group),
                    "kept": group[0].get("key"),
                    "titles": [item.get("title") for item in group],
                }
            )
    unique.sort(key=lambda item: (item.get("project_relevance") or 0, item.get("year") or 0), reverse=True)
    return unique, duplicates


def build_topic_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    top_by_topic: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        for topic in entry.get("topics", []):
            counts[topic] += 1
    for topic in sorted(counts):
        matched = [entry for entry in entries if topic in entry.get("topics", [])]
        matched.sort(key=lambda item: (item.get("project_relevance") or 0, item.get("year") or 0), reverse=True)
        top_by_topic[topic] = [reference_stub(item) for item in matched[:8]]
    return {
        "counts": dict(counts.most_common()),
        "top_by_topic": top_by_topic,
    }


def reference_stub(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": entry.get("key"),
        "title": entry.get("title"),
        "year": entry.get("year"),
        "doi": entry.get("doi"),
        "url": entry.get("url"),
        "journal": entry.get("journal"),
        "topics": entry.get("topics", []),
        "project_relevance": entry.get("project_relevance"),
        "read_status": entry.get("read_status"),
        "has_pdf": entry.get("has_pdf"),
    }


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001 - keep digest generation resilient.
        return {"_load_error": str(exc), "_path": str(path)}


def build_digest(library_dir: Path = LIBRARY_DIR, output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    bib_files = find_bibtex_files(library_dir)
    entries: list[dict[str, Any]] = []
    source_stats = []
    for bib_file in bib_files:
        text = bib_file.read_text(encoding="utf-8", errors="ignore")
        raw_entries = iter_bibtex_entries(text)
        source_stats.append({"path": str(bib_file), "raw_entry_count": len(raw_entries)})
        entries.extend(compact_entry(raw, bib_file.parent, bib_file) for raw in raw_entries)

    unique_entries, duplicate_groups = dedupe_entries(entries)
    years = [entry["year"] for entry in unique_entries if isinstance(entry.get("year"), int)]
    type_counts = Counter(entry.get("entry_type") or "unknown" for entry in unique_entries)
    status_counts = Counter(entry.get("read_status") or "unknown" for entry in unique_entries)
    topic_payload = build_topic_payload(unique_entries)
    recent_refs = [
        entry
        for entry in unique_entries
        if isinstance(entry.get("year"), int) and entry["year"] >= 2020
    ]
    high_interest = sorted(
        recent_refs,
        key=lambda item: (item.get("project_relevance") or 0, item.get("year") or 0),
        reverse=True,
    )[:30]
    plugin_status = load_json(library_dir / "zotero_plugin_status.json", {})
    collections_payload = load_json(library_dir / "zotero_collections.json", {})
    provider = "zotero_plugin_live_export" if any(path.name == "zotero_live_export.bib" for path in bib_files) else "manual_bibtex_export"
    digest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provider": provider,
        "source_bib_files": source_stats,
        "plugin_status": plugin_status,
        "collections": {
            "count": len(collections_payload.get("collections", []))
            if isinstance(collections_payload, dict)
            else 0,
            "tree": collections_payload.get("tree", []) if isinstance(collections_payload, dict) else [],
            "path": str(library_dir / "zotero_collections.json"),
        },
        "summary": {
            "raw_entry_count": len(entries),
            "unique_entry_count": len(unique_entries),
            "duplicate_group_count": len(duplicate_groups),
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "recent_2020_plus_count": len(recent_refs),
            "doi_count": sum(1 for entry in unique_entries if entry.get("doi")),
            "abstract_count": sum(1 for entry in unique_entries if entry.get("has_abstract")),
            "pdf_count": sum(1 for entry in unique_entries if entry.get("has_pdf")),
            "entry_type_counts": dict(type_counts.most_common()),
            "read_status_counts": dict(status_counts.most_common()),
        },
        "topics": topic_payload,
        "recent_references": [reference_stub(entry) for entry in recent_refs[:40]],
        "high_interest": [reference_stub(entry) for entry in high_interest],
        "dedupe": {"duplicate_groups": duplicate_groups[:40]},
        "entries": unique_entries,
        "usage_boundary": {
            "eureka": "read-only literature context and auditable scoring suggestions",
            "franklin": "may receive QC emphasis only; processing methods remain user-approved",
            "dashboard": "do not merge all Zotero entries into the main literature radar automatically",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(digest, f, indent=2, ensure_ascii=False)
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a compact Zotero digest for Eureka.")
    parser.add_argument("--library", default=str(LIBRARY_DIR), help="Library directory containing Zotero BibTeX export.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Digest JSON output path.")
    args = parser.parse_args()
    digest = build_digest(Path(args.library), Path(args.output))
    summary = digest["summary"]
    print(
        "Zotero digest: "
        f"{summary['unique_entry_count']} unique entries, "
        f"{summary['recent_2020_plus_count']} recent 2020+, "
        f"{len(digest['high_interest'])} high-interest references."
    )
    print(f"Output: {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
