# /write-section

Write or rewrite a paper section in PRL-style English prose, drawing from:
- The Chinese graduation thesis (`agent_workspace/thesis_text.json`)
- Eureka's literature context (`agent_workspace/eureka_corpus.json`)
- Quill's existing draft (via `manuscript_agent.py`)
- Dashboard verified data (`dashboard/dashboard_data.json`)

## Usage

```
/write-section <section>
```

Where `<section>` is one of: `abstract`, `introduction`, `methods`, `results`, `conclusions`

## MANDATORY Writing Rules

These rules MUST be followed — violations are flagged and must be fixed before `/paper-compile`.

### R1 — Data Fidelity
Every numerical claim (radius, velocity, We, Bo, Re, acceleration, frequency) must be verifiable against dashboard data. If a number appears in the paper, it must exist in `dashboard_data.json` or be derived from a traceable source. Tag unverifiable numbers with `[DATA-NEEDED]`.

### R2 — Literature Grounding
Every major scientific claim must be supported by at least one Eureka-matched reference (prefer 2020+). Use `paper_writer.fact_check_claim()` to verify. Tag unsupported claims with `[CITE-NEEDED]`.

### R3 — Blank Policy (Quill Alignment)
Unknown mechanisms, unmeasured parameters, and unconfirmed phenomena remain tagged as `[UNCONFIRMED]` — never invented. This follows Quill's policy: "Only write what has been done or observed in the dashboard."

### R4 — PRL Concision
Target PRL word budgets:

| Section | Max Words |
|---------|-----------|
| Abstract | 250 |
| Introduction | 600 |
| Methods | 800 |
| Results | 1200 |
| Conclusions | 400 |

If content exceeds budget, flag for compression with `[COMPRESS]`.

### R5 — Dual-Model Clarity
The primary narrative is **antibubble formation via PB method** (graduation thesis). Rigid ball experiments appear as **comparison/control**, never as the main story. Clearly separate:
- **Droplet-PB interaction** → main results (antibubble formation criteria)
- **Rigid sphere-PB interaction** → supplementary (confined particle transport as comparison)

### R6 — Terminology Consistency
Use the standard terminology map from `paper_writer.build_prl_term_map()`. Key pairs:
- "反气泡" → "antibubble"
- "Plateau Border/PB" → "Plateau border (PB)" on first use, then "PB"
- "多层结构" → "multi-layer structure"
- "包裹" → "packing"
- "夹断" → "pinch-off"
- "准则" → "criterion" (singular), "criteria" (plural)
- "液滴" → "droplet" (NOT "drop")

## Workflow

1. **Load context**:
   ```python
   from paper_writer import load_all_writing_context, PRL_BUDGETS
   ctx = load_all_writing_context()
   ```

2. **Extract source material**:
   - For introduction: `ctx["thesis"]["chapters"]["chapter1_introduction"]`
   - For methods: `ctx["thesis"]["chapters"]["chapter2_experimental_setup"]`
   - For results: `ctx["thesis"]["chapters"]["chapter3_dynamics"]`
   - For conclusions: `ctx["thesis"]["chapters"]["chapter4_conclusions"]`
   - Cross-reference with `ctx["quill"]["sections"]` for existing Quill draft
   - Use `ctx["eureka"]["research_digest"]` for literature citations
   - Check `ctx["dashboard"]` for verified data points

3. **Write section** following rules R1-R6:
   - Start with a short physical motivation (1-2 sentences)
   - Present specific data with error/range information
   - Cite Eureka-matched references with `\cite{}` keys from `zotero_live_export.bib`
   - End with a transition or summary hook

4. **Save output**:
   ```python
   from paper_writer import save_section
   save_section(section_name, {
       "title": "...",
       "body": "markdown text...",
       "latex": "LaTeX text...",
       "word_count": N,
       "rules_check": {"R1": True, "R2": True, ...},
       "status": "draft",
   })
   ```

5. **Report**:
   - Display word count vs budget
   - List all `[DATA-NEEDED]`, `[CITE-NEEDED]`, `[UNCONFIRMED]`, `[COMPRESS]` tags
   - List Eureka references cited
   - List dashboard data points used

## Example Output Format

After writing, display:
```
✅ Section: Introduction
   Words: 580 / 600 (budget)
   Rules: R1 ✓ | R2 ✓ | R3 ✓ | R4 ✓ | R5 ✓ | R6 ✓
   Citations: [cite1], [cite2], ...
   Data sources: dashboard cases 01_PP_freefall, ...
   Tags: none
```
