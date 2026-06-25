# Antibubble PRL Manuscript — Overleaf Package

## Files

| File | Description |
|------|-------------|
| `main.tex` | Main manuscript (PRL format, revtex4-2) |
| `Supplementary_Material.tex` | Supplementary Material with full derivations |
| `references.bib` | Bibliography (Zotero live export, 215 entries) |
| `figures/` | Paper figures (8 PNG files) |

## Figures

| File | Paper Figure | Content |
|------|-------------|---------|
| `fig1_setup_a.png` | Fig. 1(a) | Experimental setup schematic |
| `fig1_setup_b.png` | Fig. 1(b) | PB frame design |
| `fig2_stages.png` | Fig. 2(a) | Four stages of droplet-PB interaction |
| `fig2_outcomes.png` | Fig. 2(b-d) | Three outcomes |
| `fig3_webo_atm.png` | Fig. 3(a) | We-Bo phase diagram (atmospheric) |
| `fig3_webo_vacuum.png` | Fig. 3(b) | We-Bo phase diagram (varying P) |
| `fig4_combined.png` | Fig. 4(a) | Combined phase diagram |
| `fig4_schematic.png` | Fig. 4(b) | Gas film schematic |

## Compilation

Upload entire folder to Overleaf. Compile with:
1. `main.tex` (pdfLaTeX → BibTeX → pdfLaTeX × 2)
2. `Supplementary_Material.tex` separately

## Key theory framework (2026-06-25)

- **Two criteria**: We-Bo (energy, Stage 2) + t_p/t_d (gas drainage, Stage 2→3)
- **Coupled model**: PB film + droplet + gas film, n=2 mode preserves gas volume
- **Cyclic shuttling**: Gas cycles between pocket ↔ thin film (NOT RC decay)
- **Collapse number**: C = α³ × f × t_trans / (V_p/V_f)
- **Oscillation dominates gravity**: τ_g/t_trans ~ 24, v_osc/v_g ~ 5.4
- **Parallel transport**: Droplet (deformable) vs rigid sphere (rigid) comparison
