# Paper figure cache

Eureka uses this folder as the literature-radar image cache.

Recommended workflow:

```powershell
python paper_figure_fetcher.py --limit 14 --force
python dashboard_builder.py
```

The fetcher tries DOI pages, EuropePMC/Crossref metadata, publisher images, and ScienceDirect graphical abstracts. If a real paper image cannot be fetched, it creates an automatic result-summary visual so the radar never falls back to an empty placeholder.

Manual images are still supported: use a filename containing either the DOI or a recognizable title fragment.
