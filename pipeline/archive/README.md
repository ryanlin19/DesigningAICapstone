# Archived scripts

One-off scripts from building the board (Oct 22-29, 2026). Nothing in the build or the refresh uses them. They are kept
in case a question comes up again, and still run from here (for example `python pipeline/archive/inspect_build.py`).

- `spike_*` - first look at which companies have a readable job board and what the classifier keeps
- `inspect_*`, `check_*`, `probe_deadline_fields.py`, `probe_mba.py`, `kearney_titles.py` - checks on the built data used
  while designing the location, deadline, MBA and visa rules
- `survey_ats.py` - which job system each large firm's careers page uses
- `test_custom.py` - early trial of the firm-specific readers
- `h1b.py`, `test_h1b.py`, `check_h1b_matches.py` - USCIS H-1B history, no longer used (decided 2026-10-23)
- `seed_history.py` - started `data/history.json` once. **Do not run it again**: it would reset the "What's new" history.
