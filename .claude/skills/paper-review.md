# /paper-review

Review a written paper section against ALL mandatory writing rules. This is a quality gate — sections that fail review must be revised before `/paper-compile`.

## Usage

```
/paper-review [section]
```

- With section name (e.g., `/paper-review introduction`): review only that section
- Without argument (`/paper-review`): review all sections

## Review Dimensions

### Dimension 1: Data Consistency (R1)
Cross-check every numerical claim against `dashboard_data.json`:
- Material properties (density, surface tension, viscosity) → check against experiment config
- Case metrics (radius, velocity, acceleration, frequency) → check against processed data
- Experimental parameters (fps, pixel_per_mm, ROI) → check against `case_registry.json`
- Derived quantities (We, Bo, Re) → verify calculation with source values

Flag as:
- `[CONFIRMED]` — value matches dashboard exactly
- `[APPROXIMATE]` — value rounds to dashboard value
- `[MISMATCH]` — value contradicts dashboard

### Dimension 2: Literature Alignment (R2, R8)
Verify literature references:
- Every `\cite{}` must have a corresponding entry in `zotero_live_export.bib`
- Major claims should cite recent (2020+) literature from Eureka's themes
- Check that citations from the Chinese thesis are translated to their English original sources
- Verify no "phantom citations" (cite keys with no bib entry)

### Dimension 3: Terminology (R6, R7)
Scan for terminology violations:
- Chinese terms that should be translated
- Inconsistent abbreviations (e.g., "PB" vs "Plateau border" usage)
- Non-standard terms (check against `paper_writer.build_prl_term_map()`)
- Unit formatting (SI conventions)

### Dimension 4: PRL Style (R4)
Check PRL compliance:
- Word count per section vs budget
- Sentence length (flag sentences >40 words)
- Active vs passive voice balance
- Abstract structure (problem -> method -> key result -> significance)
- Title clarity and length

### Dimension 5: Structural Completeness (R3)
Check that:
- All required sections exist (Abstract, Introduction, Methods, Results, Conclusions)
- `[DATA-NEEDED]`, `[CITE-NEEDED]`, `[UNCONFIRMED]` tags are resolved or explicitly acknowledged
- Figures are referenced (Fig. 1, Fig. 2, etc.)
- Appendix or supplementary materials are referenced where needed

### Dimension 6: Dual-Model Narrative (R5)
Verify:
- Antibubble formation is the primary narrative
- Rigid ball data is clearly positioned as comparison/control
- Transitions between droplet-PB and rigid sphere-PB are clearly signaled
- Conclusions distinguish between antibubble formation criteria and particle transport observations

## Workflow

1. **Load the section(s)** from `agent_workspace/paper_sections/<section>.md`
2. **Load reference data** via `paper_writer.load_all_writing_context()`
3. **Run automated checks** via `paper_writer.fact_check_claim()`
4. **Manual review** of style, narrative flow, terminology
5. **Generate review report** via `paper_writer.save_review_report()`
6. **Update writing state** to mark section as reviewed

## Output Format

After review, display:
```
📋 Review: <section>
   Date: <timestamp>

   Dimension 1 — Data Consistency:  X/Y passed
   Dimension 2 — Literature:       X/Y passed
   Dimension 3 — Terminology:      X/Y passed
   Dimension 4 — PRL Style:        X/Y passed
   Dimension 5 — Completeness:     X/Y passed
   Dimension 6 — Narrative:        X/Y passed

   Critical issues: N
   Warnings: M
   Verdict: [PASS] or [NEEDS REVISION]
```

If CRITICAL issues exist, list each one with the specific text, the rule violated, and a suggested fix. If PASS, update `writing_state.json` to mark the section as `reviewed: true`.
