# /paper-sync

Synchronize ALL paper writing data sources to their latest state. Run this at the start of each writing session and after any data changes.

## Usage

```
/paper-sync [--force]
```

- `--force`: Regenerate all data even if no changes detected

## What It Does

1. **Refresh Quill session state**:
   ```bash
   python quill_session_refresh.py --force
   ```
   This updates: dashboard data, Zotero digest, Quill session brief

2. **Rebuild Eureka corpus** (if library changed):
   ```bash
   python eureka_agent.py --library "library" --output "agent_workspace/eureka_corpus.json"
   ```
   This updates: literature corpus, research digest, themes

3. **Regenerate Quill draft**:
   ```bash
   python -c "from paper_writer import load_quill_draft; d = load_quill_draft(); print(f'Quill progress: {d[\"progress\"].get(\"percent\", \"?\")}%')"
   ```

4. **Validate writing context**:
   ```python
   from paper_writer import load_all_writing_context, get_writing_state
   ctx = load_all_writing_context()
   state = get_writing_state()
   ```

5. **Report changes**:
   - New/modified raw data files
   - Newly processed cases
   - Updated literature entries
   - Changed dashboard data
   - Paper section status updates

## Output

Display a synchronization summary:
```
🔄 Paper Sync — <timestamp>

   Data:
   - Raw cases: N (N new since last sync)
   - Processed: N (top: <case_id>, score: <score>)
   - Dashboard: N cases, N runs

   Literature:
   - Eureka entries: N (N recent, 2020+)
   - Zotero: N unique, N PDFs
   - Themes: <list top 3>

   Paper:
   - Sections written: N/5
   - Sections reviewed: N/5
   - Overall progress: X%
   - Quill stage: <stage>

   Actions taken: <list>
```

## Integration with Writing Rules

After sync, verify:
- **R1**: Dashboard data is current for fact-checking
- **R2**: Eureka references are up-to-date for citations
- **R8**: Zotero bib is ready for `\cite{}` resolution
