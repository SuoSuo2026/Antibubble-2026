"""
Paper Writer — bridges the Chinese graduation thesis, Eureka literature corpus,
Quill manuscript draft, and dashboard data for PRL-style English paper writing.

Invoked by Claude Code skills: /write-section, /paper-review, /paper-sync, /paper-compile
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
LIBRARY_DIR = BASE_DIR / "library"
AGENT_DIR = BASE_DIR / "agent_workspace"
PAPER_SECTIONS_DIR = AGENT_DIR / "paper_sections"
REVIEW_REPORTS_DIR = AGENT_DIR / "review_reports"
THESIS_TEXT_PATH = AGENT_DIR / "thesis_text.json"
EUREKA_CORPUS_PATH = AGENT_DIR / "eureka_corpus.json"
EUREKA_PROFILE_PATH = AGENT_DIR / "eureka_profile.json"
QUILL_STATE_PATH = AGENT_DIR / "quill_session_state.json"
DASHBOARD_DATA_PATH = BASE_DIR / "dashboard" / "dashboard_data.json"
WRITING_STATE_PATH = AGENT_DIR / "writing_state.json"
MANUSCRIPT_TEX_PATH = LIBRARY_DIR / "Manuscript.tex"

# ── PRL word budgets ───────────────────────────────────────────────
PRL_BUDGETS = {
    "abstract": 250,
    "introduction": 600,
    "methods": 800,
    "results": 1200,
    "conclusions": 400,
}


# ── Loaders ──────────────────────────────────────────────────────────

def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        return {"_load_error": str(exc), "_path": str(path)}


def load_thesis_text() -> dict[str, Any]:
    """Load the full Chinese graduation thesis text."""
    data = load_json(THESIS_TEXT_PATH, {})
    paragraphs = data.get("paragraphs", [])
    return {
        "total_paragraphs": data.get("total_paragraphs", 0),
        "paragraphs": paragraphs,
        # Map to sections by chapter markers
        "chapters": _split_thesis_into_chapters(paragraphs),
    }


def _split_thesis_into_chapters(paragraphs: list[str]) -> dict[str, list[str]]:
    """Heuristically split thesis paragraphs into chapters based on Chinese headers."""
    chapters: dict[str, list[str]] = {}
    current_chapter = "preamble"
    chapters[current_chapter] = []

    chapter_patterns = [
        (r"引言|研究背景|研究现状|研究主题", "chapter1_introduction"),
        (r"反气泡制备装置|实验装置|第2章|第二章", "chapter2_experimental_setup"),
        (r"反气泡生成的动力学|动力学研究|第3章|第三章", "chapter3_dynamics"),
        (r"总结与展望|第4章|第四章", "chapter4_conclusions"),
        (r"外文资料的书面翻译|书面翻译|附录", "appendix_translation"),
        (r"插图索引|附表清单|参考文献|致谢|声明", "back_matter"),
    ]

    for para in paragraphs:
        matched = False
        for pattern, chapter_name in chapter_patterns:
            if re.search(pattern, para):
                if chapter_name not in chapters:
                    chapters[chapter_name] = []
                current_chapter = chapter_name
                matched = True
                break
        chapters[current_chapter].append(para)

    return chapters


def load_eureka_context() -> dict[str, Any]:
    """Load Eureka's literature research digest."""
    corpus = load_json(EUREKA_CORPUS_PATH, {})
    profile = load_json(EUREKA_PROFILE_PATH, {})

    research_digest = corpus.get("research_digest", {})
    return {
        "research_digest": research_digest,
        "themes": research_digest.get("themes", []),
        "recent_references": research_digest.get("recent_references", []),
        "stack_highlights": research_digest.get("stack_highlights", []),
        "pb_particle_brief": research_digest.get("pb_particle_brief", {}),
        "key_conclusions": research_digest.get("key_conclusions", []),
        "future_work": research_digest.get("future_work", []),
        "optimization_backlog": research_digest.get("optimization_backlog", []),
        "zotero_context": research_digest.get("zotero_context", {}),
        "recent_count": research_digest.get("recent_count", 0),
        "library_summary": corpus.get("summary", {}),
        "franklin_training": profile.get("franklin_training", {}),
    }


def load_quill_draft() -> dict[str, Any]:
    """Load Quill's current manuscript draft by running manuscript_agent."""
    try:
        from manuscript_agent import build_manuscript_draft, load_manuscript_context

        # Try to load dashboard data for cases
        dashboard = load_json(DASHBOARD_DATA_PATH, {})
        cases = dashboard.get("cases", []) if isinstance(dashboard, dict) else []

        eureka_ctx = load_eureka_context()
        research = eureka_ctx.get("research_digest", {})

        draft = build_manuscript_draft(cases, research)
        return draft
    except Exception as exc:
        return {
            "_load_error": str(exc),
            "sections": [],
            "progress": {},
            "latex": "",
        }


def load_dashboard_data() -> dict[str, Any]:
    """Load the latest dashboard data for paper fact-checking."""
    return load_json(DASHBOARD_DATA_PATH, {})


def load_manuscript_template() -> str:
    """Load the Manuscript.tex template."""
    if MANUSCRIPT_TEX_PATH.exists():
        return MANUSCRIPT_TEX_PATH.read_text(encoding="utf-8", errors="ignore")
    return ""


def load_all_writing_context() -> dict[str, Any]:
    """Load everything needed for paper writing."""
    return {
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
        "thesis": load_thesis_text(),
        "eureka": load_eureka_context(),
        "quill": load_quill_draft(),
        "dashboard": load_dashboard_data(),
        "template": load_manuscript_template(),
    }


# ── Writers ──────────────────────────────────────────────────────────

def save_section(section_name: str, content: dict[str, Any]) -> Path:
    """Save a paper section as both .md and .tex files.

    Args:
        section_name: One of abstract, introduction, methods, results, conclusions
        content: Dict with 'title', 'body' (markdown), 'latex' (LaTeX), 'word_count', 'rules_check'
    """
    PAPER_SECTIONS_DIR.mkdir(parents=True, exist_ok=True)

    md_path = PAPER_SECTIONS_DIR / f"{section_name}.md"
    tex_path = PAPER_SECTIONS_DIR / f"{section_name}.tex"

    # Write markdown
    md_text = f"# {content.get('title', section_name.title())}\n\n"
    md_text += f"> Word count: {content.get('word_count', 0)} / {PRL_BUDGETS.get(section_name, 'N/A')}\n"
    md_text += f"> Generated: {content.get('generated_at', datetime.now().isoformat())}\n"
    md_text += f"> Rules check: {content.get('rules_check', {})}\n\n"
    md_text += content.get("body", "")

    md_path.write_text(md_text, encoding="utf-8")

    # Write LaTeX
    latex_text = content.get("latex", content.get("body", ""))
    tex_path.write_text(latex_text, encoding="utf-8")

    # Update writing state
    _update_writing_state(section_name, content)

    return md_path


def _update_writing_state(section_name: str, content: dict[str, Any]) -> None:
    """Track which sections have been written and reviewed."""
    state = load_json(WRITING_STATE_PATH, {})
    state.setdefault("sections", {})
    state["sections"][section_name] = {
        "status": content.get("status", "draft"),
        "word_count": content.get("word_count", 0),
        "generated_at": content.get("generated_at", datetime.now().isoformat(timespec="seconds")),
        "reviewed": content.get("reviewed", False),
        "rules_check": content.get("rules_check", {}),
    }
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with WRITING_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_writing_state() -> dict[str, Any]:
    """Get current writing progress state."""
    state = load_json(WRITING_STATE_PATH, {})
    sections = state.get("sections", {})

    # Compute overall progress
    required = ["abstract", "introduction", "methods", "results", "conclusions"]
    written = sum(1 for s in required if s in sections and sections[s].get("status") == "final")
    reviewed = sum(1 for s in required if s in sections and sections[s].get("reviewed"))

    return {
        "sections": sections,
        "written_count": written,
        "reviewed_count": reviewed,
        "total_required": len(required),
        "progress_pct": round(written / len(required) * 100),
        "updated_at": state.get("updated_at"),
    }


def save_review_report(section_name: str, report: dict[str, Any]) -> Path:
    """Save a review report for a section."""
    REVIEW_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"paper_review_{section_name}_{timestamp}.md"
    path = REVIEW_REPORTS_DIR / filename

    lines = [
        f"# Paper Review: {section_name}",
        f"- Date: {datetime.now().isoformat(timespec='seconds')}",
        f"- Section: {section_name}",
        "",
        "## Confirmed Claims",
    ]
    for claim in report.get("confirmed", []):
        lines.append(f"- ✅ {claim}")

    lines.append("")
    lines.append("## Unverified / Flagged Claims")
    for claim in report.get("unverified", []):
        lines.append(f"- ⚠️ {claim}")

    lines.append("")
    lines.append("## Terminology Issues")
    for issue in report.get("terminology_issues", []):
        lines.append(f"- 📝 {issue}")

    lines.append("")
    lines.append("## Missing Citations")
    for cite in report.get("missing_citations", []):
        lines.append(f"- 🔗 {cite}")

    lines.append("")
    lines.append("## Style Issues")
    for issue in report.get("style_issues", []):
        lines.append(f"- ✂️ {issue}")

    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Total issues: {len(report.get('unverified', [])) + len(report.get('terminology_issues', [])) + len(report.get('missing_citations', [])) + len(report.get('style_issues', []))}")
    lines.append(f"- Verdict: {'✅ PASS' if report.get('pass', False) else '🔴 NEEDS REVISION'}")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def compile_manuscript() -> dict[str, Any]:
    """Fill Manuscript.tex with generated sections and return the final LaTeX."""
    template = load_manuscript_template()
    if not template:
        return {"error": "Manuscript.tex template not found"}

    # Collect all sections
    sections = {}
    for name in ["abstract", "introduction", "methods", "results", "conclusions"]:
        tex_path = PAPER_SECTIONS_DIR / f"{name}.tex"
        if tex_path.exists():
            sections[name] = tex_path.read_text(encoding="utf-8")
        else:
            sections[name] = None

    # Build the filled template
    # Extract preamble (everything before \begin{document})
    preamble_end = template.find(r"\begin{document}")
    if preamble_end == -1:
        preamble = template
        body_start = 0
    else:
        preamble = template[:preamble_end]
        body_start = preamble_end + len(r"\begin{document}")

    # Find abstract and replace
    abstract_start = template.find(r"\begin{abstract}")
    abstract_end = template.find(r"\end{abstract}")
    filled = template
    if abstract_start != -1 and abstract_end != -1 and sections.get("abstract"):
        filled = (
            filled[:abstract_start]
            + r"\begin{abstract}" + "\n"
            + sections["abstract"]
            + "\n" + r"\end{abstract}"
            + filled[abstract_end + len(r"\end{abstract}"):]
        )

    # Replace Introduction section (textcolor{cyan}... to next \textcolor)
    intro_pattern = re.compile(
        r'(\\textcolor\{cyan\}\{\\textbf\{Introduction\}\}.*?)(?=\\textcolor\{cyan\})',
        re.DOTALL,
    )
    if sections.get("introduction"):
        intro_replacement = r"\textcolor{cyan}{\textbf{Introduction}}\par\n" + sections["introduction"]
        filled = intro_pattern.sub(intro_replacement, filled)

    # Replace Experimental Setup
    exp_pattern = re.compile(
        r'(\\textcolor\{cyan\}\{\\textbf\{Experimental Setup\}\}.*?)(?=\\textcolor\{cyan\})',
        re.DOTALL,
    )
    if sections.get("methods"):
        exp_replacement = r"\textcolor{cyan}{\textbf{Experimental Methods}}\par\n" + sections["methods"]
        filled = exp_pattern.sub(exp_replacement, filled)

    # Replace Results
    results_pattern = re.compile(
        r'(\\textcolor\{cyan\}\{\\textbf\{Results and discussion\}\}.*?)(?=\\textcolor\{cyan\})',
        re.DOTALL,
    )
    if sections.get("results"):
        res_replacement = r"\textcolor{cyan}{\textbf{Results and Discussion}}\par\n" + sections["results"]
        filled = results_pattern.sub(res_replacement, filled)

    # Replace Conclusions
    concl_pattern = re.compile(
        r'(\\textcolor\{cyan\}\{\\textbf\{Conclusions\}\}.*?)(?=\\begin\{acknowledgements\})',
        re.DOTALL,
    )
    if sections.get("conclusions"):
        concl_replacement = r"\textcolor{cyan}{\textbf{Conclusions}}\par\n" + sections["conclusions"] + "\n\n"
        filled = concl_pattern.sub(concl_replacement, filled)

    # Write filled manuscript
    filled_path = LIBRARY_DIR / "Manuscript_filled.tex"
    filled_path.write_text(filled, encoding="utf-8")

    return {
        "output_path": str(filled_path),
        "sections_filled": [s for s, v in sections.items() if v],
        "sections_missing": [s for s, v in sections.items() if not v],
    }


# ── Fact-checking utilities ──────────────────────────────────────────

def fact_check_claim(claim: str, dashboard: dict[str, Any], eureka: dict[str, Any]) -> dict[str, Any]:
    """Check a single claim against dashboard data and literature context.

    Returns:
        {"status": "confirmed"|"unverified"|"contradicted", "evidence": [...]}
    """
    evidence = []

    # Check for numerical claims against dashboard
    cases = dashboard.get("cases", []) if isinstance(dashboard, dict) else []
    summary = dashboard.get("summary", {}) if isinstance(dashboard, dict) else {}

    # Extract numbers from claim
    numbers = re.findall(r"\b(\d+\.?\d*)\s*(mm|mm/s|m/s|Hz|%|g/cm³|mN/m|atm)\b", claim)

    # Check for material names
    materials = ["PP", "PMMA", "PS", "POM"]
    for m in materials:
        if m in claim:
            # Can we find this material in dashboard?
            found = [c for c in cases if (c.get("metrics") or {}).get("material") == m]
            if found:
                evidence.append(f"Material '{m}' found in {len(found)} dashboard cases")
            else:
                evidence.append(f"WARNING: Material '{m}' not found in dashboard data")

    # Check for We, Bo, Re number mentions
    if re.search(r"\bWe\b", claim):
        evidence.append("We number reference — verify against phase diagram data")
    if re.search(r"\bBo\b", claim):
        evidence.append("Bo number reference — verify against phase diagram data")

    # Check literature claims
    for theme in eureka.get("research_digest", {}).get("themes", []):
        for ref in theme.get("references", []):
            if ref.get("title") and claim.lower() in ref["title"].lower():
                evidence.append(f"Claim matches Eureka reference: {ref['title'][:100]}")

    status = "confirmed" if evidence and not any(e.startswith("WARNING") for e in evidence) else "unverified"
    if any(e.startswith("WARNING") for e in evidence):
        status = "contradicted"

    return {"status": status, "evidence": evidence}


def build_prl_term_map() -> dict[str, str]:
    """Standard terminology for PRL-style paper."""
    return {
        "反气泡": "antibubble",
        "气泡": "bubble",
        "液膜": "liquid film",
        "气膜": "air film / gas film",
        "Plateau Border / PB": "Plateau border (PB)",
        "液滴": "droplet",
        "夹断": "pinch-off",
        "包裹": "packing (multi-layer formation)",
        "多层结构": "multi-layer (1G1L) structure",
        "泡沫生成法": "foam-based generation method",
        "韦伯数 We": "Weber number (We)",
        "邦德数 Bo": "Bond number (Bo)",
        "准则": "criterion",
        "相图": "phase diagram",
        "表面活性剂": "surfactant",
        "三棱柱框架": "triangular prism frame",
        "注射泵": "syringe pump",
        "高速相机": "high-speed camera",
        "能量守恒": "energy conservation",
        "润滑理论": "lubrication theory",
        "特征时间": "characteristic time",
        "超声造影": "ultrasound imaging/contrast",
        "药物输运": "drug delivery",
        "自由落体": "free fall",
        "真空箱": "vacuum chamber",
        "环境压力": "ambient pressure",
        "硬质小球": "rigid particle / rigid sphere",
    }


if __name__ == "__main__":
    ctx = load_all_writing_context()
    print("=== Writing Context Loaded ===")
    print(f"Thesis paragraphs: {ctx['thesis']['total_paragraphs']}")
    print(f"Eureka themes: {len(ctx['eureka']['themes'])}")
    print(f"Quill progress: {ctx['quill'].get('progress', {}).get('percent', 'N/A')}%")
    print(f"Dashboard cases: {len(ctx['dashboard'].get('cases', []))}")
    print(f"Template length: {len(ctx['template'])} chars")
    print(f"Thesis chapters: {list(ctx['thesis']['chapters'].keys())}")
    state = get_writing_state()
    print(f"Writing progress: {state['progress_pct']}% ({state['written_count']}/{state['total_required']} sections)")
