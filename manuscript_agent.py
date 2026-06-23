from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
LIBRARY_DIR = BASE_DIR / "library"
MANUSCRIPT_DIR = LIBRARY_DIR / "manuscript"


def _fmt(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:.{digits}f}"


def _section(title: str, paragraphs: list[str]) -> dict[str, Any]:
    clean = [item for item in paragraphs if item and item.strip()]
    return {
        "title": title,
        "body": "\n\n".join(clean),
        "latex": "\n\n".join(_latex_escape(item) for item in clean),
        "missing": [] if clean else ["Insufficient evidence; left blank for now."],
    }


def _latex_escape(text: str) -> str:
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(repl.get(ch, ch) for ch in text)


def _is_rigid(case: dict[str, Any]) -> bool:
    metrics = case.get("metrics") or {}
    return str(metrics.get("experiment_type") or "").lower() == "rigid_ball"


def load_manuscript_context(path: Path = MANUSCRIPT_DIR) -> dict[str, Any]:
    path.mkdir(parents=True, exist_ok=True)
    files = []
    snippets = []
    candidates = list(path.glob("*")) + list(LIBRARY_DIR.glob("*.pdf")) + list(LIBRARY_DIR.glob("*.tex"))
    seen = set()
    for item in sorted(candidates):
        if not item.is_file():
            continue
        if item.resolve() in seen:
            continue
        seen.add(item.resolve())
        if item.suffix.lower() not in {".tex", ".txt", ".md", ".pdf"}:
            continue
        record = {"name": item.name, "path": str(item), "kind": item.suffix.lower().lstrip(".")}
        files.append(record)
        if item.suffix.lower() in {".tex", ".txt", ".md"}:
            text = item.read_text(encoding="utf-8", errors="ignore")
            snippets.append({"name": item.name, "text": text[:4000]})
        elif item.suffix.lower() == ".pdf":
            snippets.append({"name": item.name, "text": extract_pdf_text(item)[:4000] or "PDF reference available; text extraction pending or external."})
    return {"files": files, "snippets": snippets}


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:
            return ""
    try:
        reader = PdfReader(str(path))
        chunks = []
        for page in reader.pages[:8]:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks).strip()
    except Exception:
        return ""


def build_manuscript_draft(cases: list[dict[str, Any]], research: dict[str, Any]) -> dict[str, Any]:
    manuscript_context = load_manuscript_context()
    processed = [case for case in cases if case.get("best_run_id")]
    rigid = [case for case in processed if _is_rigid(case)]
    droplets = [case for case in processed if not _is_rigid(case)]
    materials = sorted({str((case.get("metrics") or {}).get("material")) for case in rigid if (case.get("metrics") or {}).get("material")})
    recent_count = research.get("recent_count")
    theme_names = [theme.get("name") for theme in research.get("themes", []) if theme.get("name")]

    intro = _section(
        "Introduction",
        [
            (
                "Transport through Plateau borders and thin liquid films couples confinement, interfacial deformation, capillary drainage, and inertia--viscous crossover. "
                f"The current literature map contains {recent_count} recent papers and organizes the field into: {', '.join(theme_names)}."
            )
            if recent_count
            else "",
            (
                "Here we focus on the transport of antibubble-like droplets and rigid particles in the vicinity of Plateau borders and liquid films. "
                "Rigid particles are treated separately from oscillating droplets; their analysis is based on trajectory continuity, radius stability, and particle--interface interactions."
            )
            if rigid
            else "",
        ],
    )

    method_bits = []
    if processed:
        method_bits.append(
            "Image sequences were processed by a local agent workflow. Sisyphus monitors raw data and triggers processing; Franklin scores tracking, radius stability, and fit quality; Eureka provides literature-grounded observations without changing the processing pipeline."
        )
    if rigid:
        method_bits.append(
            "Rigid-particle cases were tracked by detecting the particle center and equivalent radius. The primary direction is taken as x unless the measured displacement indicates otherwise. Velocity and acceleration are obtained from smoothed or polynomial fits to the position trace."
        )
    if droplets:
        method_bits.append(
            "Droplet and encapsulated-object cases retain radius, acceleration fits, and oscillation-frequency metrics. When a contact or coalescence event changes the dynamics, the valid-frame window is split before interpretation."
        )
    methods = _section("Experimental Methods and Data Processing", method_bits)

    result_bits = []
    if rigid:
        result_bits.append(
            f"We have processed {len(rigid)} rigid-particle cases with materials including {', '.join(materials) if materials else '[to be specified]'}. "
            "For each case, the dashboard reports radius, velocity, x--t quadratic acceleration, radius fluctuation, and center-jump diagnostics."
        )
        high = [case for case in rigid if (case.get("best_score") or 0) >= 85]
        if high:
            result_bits.append(
                f"{len(high)} rigid-particle cases reach a high Franklin confidence score. Cases with radius or center jumps are flagged for review rather than used directly for physical interpretation."
            )
    if droplets:
        result_bits.append(
            f"{len(droplets)} droplet or encapsulated-object cases are retained as a comparison set, with frequency, acceleration-fit, and radius-fluctuation metrics."
        )
    results = _section("Results and Analysis", result_bits)

    conclusion = _section(
        "Conclusions",
        [
            (
                "The current workflow synchronizes raw data, processed results, quality scores, literature context, and phase-space metadata in a local dashboard. "
                "The available results motivate separate models for rigid particles and droplet-like objects: the former emphasizes identity continuity and confined-particle transport, whereas the latter retains oscillation and low-dissipation transport metrics."
            )
            if processed
            else "",
            "Further experiments should expand the radius, material, and incident-condition space for rigid particle--film or particle--Plateau-border interactions, and add dimensionless groups such as Re, We, Bo, and Ca to the phase diagram.",
        ],
    )

    sections = [intro, methods, results, conclusion]
    latex = "\n\n".join(
        f"\\section{{{_latex_escape(section['title'])}}}\n{section['latex'] or '% TODO: insufficient evidence; left blank for now.'}"
        for section in sections
    )
    progress = estimate_manuscript_progress(cases, research, manuscript_context, sections)
    return {
        "agent": {
            "name": "Quill",
            "role": "Manuscript writing agent",
            "scope": "Drafts English PRL/JFM-style text from completed data and literature context; unknown content remains blank.",
        },
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "language": "English",
        "style_target": "PRL/JFM concise physical narrative",
        "reference_context": manuscript_context,
        "critical_absorption_note": "Existing manuscript files are old-version references for tone and known background only; current claims are governed by dashboard data and recent Eureka literature.",
        "progress": progress,
        "sections": sections,
        "latex": latex,
        "policy": "Only write what has been done or observed in the dashboard. Leave unknown mechanisms, parameters, and claims blank.",
    }


def estimate_manuscript_progress(
    cases: list[dict[str, Any]],
    research: dict[str, Any],
    manuscript_context: dict[str, Any],
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    processed = [case for case in cases if case.get("best_run_id")]
    high_score = [case for case in processed if (case.get("best_score") or 0) >= 85]
    recent_count = int(research.get("recent_count") or 0)
    has_old_manuscript = any(file.get("kind") in {"tex", "pdf"} for file in manuscript_context.get("files", []))
    filled_sections = sum(1 for section in sections if section.get("body"))

    data_score = min(25, len(processed) * 1.2 + len(high_score) * 0.8)
    literature_score = min(20, recent_count * 0.3 + (5 if research.get("stack_highlights") else 0))
    writing_score = min(20, filled_sections * 2.5 + (4 if has_old_manuscript else 0))
    novelty_score = 12 if any(case for case in processed if str((case.get("metrics") or {}).get("experiment_type", "")).lower() == "rigid_ball") else 5
    percent = round(min(100, data_score + literature_score + writing_score + novelty_score))

    if percent >= 75:
        stage = "full draft consolidation"
    elif percent >= 50:
        stage = "results-driven drafting"
    elif percent >= 30:
        stage = "framework established"
    else:
        stage = "early exploration"

    daily_push = []
    if processed:
        daily_push.append(f"{len(processed)} processed cases are now connected to manuscript drafting.")
    if recent_count:
        daily_push.append(f"Eureka currently tracks {recent_count} recent references.")
    if has_old_manuscript:
        daily_push.append("An old manuscript/PDF/TEX reference is available for critical style absorption.")

    return {
        "percent": percent,
        "stage": stage,
        "innovation_level": "medium-high" if novelty_score >= 10 and recent_count >= 20 else "medium",
        "data_score": round(data_score, 1),
        "literature_score": round(literature_score, 1),
        "writing_score": round(writing_score, 1),
        "novelty_score": round(novelty_score, 1),
        "daily_push": daily_push,
        "next_actions": [
            "Confirm the physical event labels for rigid-particle cases: passing, trapping, rebound, or false tracking.",
            "Add dimensionless groups to the phase-space page once fluid properties are confirmed.",
            "Move the current Introduction from framework text toward a sharper single claim after more interaction cases are processed.",
        ],
    }
