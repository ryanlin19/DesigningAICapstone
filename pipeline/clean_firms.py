"""Flatten the firm database CSV into data/firms.json.

Reads the original file read-only. The CSV has repeated column names ("Others"),
so columns are addressed by position and grouped by the section they fall in.
"""
import csv
import json
import sys
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    Path(__file__).resolve().parent.parent / "data" / "firm_database.csv"
)
OUT = Path(__file__).resolve().parent.parent / "data" / "firms.json"

# Rollup columns are regional aggregates, not offices.
ROLLUPS = {
    "North East", "Mid Atlantic", "South", "Midwest", "West", "United States",
    "Canada", "Mexico", "North America\nclick + above to expand", "Europe",
    "Asia", "Africa", "Oceania", "Middle East", "South America",
    "Non-North America\nclick + above to epand", "Others",
}


def main():
    with open(SRC, encoding="cp1252", newline="") as f:  # exported from Excel
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]

    # Section boundaries are the blank-header spacer columns.
    spacers = [i for i, h in enumerate(header) if not h.strip()]
    loc_start = 4
    ind_start = spacers[0] + 1
    fn_start = spacers[1] + 1
    fn_end = spacers[2]

    def yes_cols(r, lo, hi, skip_rollups=False):
        out = []
        for i in range(lo, hi):
            if i < len(r) and r[i].strip().lower() == "yes":
                name = header[i].strip()
                if skip_rollups and header[i] in ROLLUPS:
                    continue
                out.append(name)
        return out

    firms = []
    for r in data:
        name = (r[0] if r else "").strip()
        if not name or name.upper().startswith("DO NOT SHARE"):  # blank rows and the sheet's confidentiality footer
            continue
        firms.append({
            "name": name,
            "school_facilitated": (r[1].strip() or None),
            "visa_stance": (r[2].strip() or None),
            "size_band": (r[3].strip() or None),
            "offices": yes_cols(r, loc_start, spacers[0], skip_rollups=True),
            "industries": yes_cols(r, ind_start, spacers[1]),
            "functions": yes_cols(r, fn_start, fn_end),
            "last_modified": r[fn_end + 1].strip() if fn_end + 1 < len(r) else None,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(firms, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(firms)} firms -> {OUT}")
    print("spacers:", spacers, "| industries:", header[ind_start], "..", header[spacers[1] - 1],
          "| functions:", header[fn_start], "..", header[fn_end - 1])


if __name__ == "__main__":
    main()
