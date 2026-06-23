# /paper-compile

Compile all written and reviewed sections into the final PRL manuscript (`Manuscript_filled.tex`).

## Usage

```
/paper-compile
```

## Prerequisites

Before compiling, ALL sections must pass `/paper-review`:
- [ ] abstract — reviewed
- [ ] introduction — reviewed
- [ ] methods — reviewed
- [ ] results — reviewed
- [ ] conclusions — reviewed

If any section has not passed review, compilation is BLOCKED.

## What It Does

1. **Load all sections** from `agent_workspace/paper_sections/`
2. **Fill Manuscript.tex** template using `paper_writer.compile_manuscript()`
3. **Verify LaTeX**:
   - All `\begin{}` / `\end{}` pairs balanced
   - All `\cite{}` keys exist in `zotero_live_export.bib`
   - All `\ref{}` labels are defined
   - Figure paths are valid (`Figures/` directory)
   - No unescaped special characters in text
4. **Resolve bibliography**:
   - Copy needed entries from `zotero_live_export.bib` to `Antibubble_Library.bib`
   - Verify all cited references have entries
5. **Write output** to `library/Manuscript_filled.tex`
6. **Report** compilation status

## Output Format

```
📄 Compilation Report — <timestamp>

   Sections:
   - abstract:      [OK] 220 words
   - introduction:  [OK] 580 words
   - methods:       [OK] 750 words
   - results:       [OK] 1100 words
   - conclusions:   [OK] 350 words

   Total: ~3000 words

   LaTeX checks:
   - Brackets balanced: [OK]
   - Citations resolved: 28/28 [OK]
   - Figure references: 4 [OK]
   - Missing labels: 0 [OK]

   Output: library/Manuscript_filled.tex
   Status: [READY FOR COMPILATION]

   Next steps:
   - Run: pdflatex Manuscript_filled.tex
   - Run: bibtex Manuscript_filled
   - Run: pdflatex Manuscript_filled.tex (x2)
```

## Post-Compilation

After successful compilation:
1. Update `writing_state.json` with compilation timestamp
2. Update `todolist.md` paper progress
3. Mark milestone: `paper-draft-ready` if all sections passed
