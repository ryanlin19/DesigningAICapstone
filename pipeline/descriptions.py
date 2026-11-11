"""Full job descriptions, for reading on the board (Peter's branch).

The board data keeps only a short snippet per role; the full text lives in the download (data/raw_fetch.json,
hundreds of MB). This copies each US posting's description into a small compressed store keyed by its link,
so the board can show it on demand.

    python pipeline/descriptions.py        # data/raw_fetch.json -> data/descriptions.db

Feeds flatten formatting, so section headings and bullets are put back where they can be recognised.
"""
import re
import sqlite3
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build      # noqa: E402  (norm_url: the same link form both job sets use)
import expand     # noqa: E402  (us_ok: the same US rule)

DATA = Path(__file__).resolve().parent.parent / "data"
MAX_CHARS = 15000

_HEADINGS = (r"about (?:the |this )?(?:role|team|job|position|company|us|you)|who we are|who you are|the role|your role|"
             r"what you(?:'|’)ll (?:do|bring|need)|what we(?:'|’)re looking for|what you bring|you will|you have|"
             r"(?:key |core |primary )?responsibilities|(?:minimum |basic |preferred |required )?qualifications|requirements|"
             r"nice to have|bonus points|benefits|our benefits|perks|compensation|pay (?:range|transparency)|salary range|"
             r"why join us|why you(?:'|’)ll love|equal (?:employment )?opportunity|location|how to apply|in this role,? you will")
_HEAD_RE = re.compile(r"(?<=[.!?:)\]])\s+(" + _HEADINGS + r")\b\s*:?", re.I)


def tidy(text):
    """Flat feed text -> text with paragraph breaks before section headings and one bullet per line."""
    t = re.sub(r"[ \t\r\f\v]+", " ", text or "").strip()
    t = re.sub(r"\s*[•●▪◦·]\s+", "\n• ", t)                       # bullets
    t = _HEAD_RE.sub(lambda m: "\n\n## " + m.group(1)[0].upper() + m.group(1)[1:] + "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t[:MAX_CHARS]


def main():
    import json
    raw = json.loads((DATA / "raw_fetch.json").read_text(encoding="utf-8"))
    path = DATA / "descriptions.db"
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE descriptions (url TEXT PRIMARY KEY, company TEXT, title TEXT, text BLOB NOT NULL)")
    n = 0
    for name, hit in raw.items():
        if not hit:
            continue
        for j in hit[2]:
            desc, url = j.get("description") or "", build.norm_url(j.get("url") or "")
            if not desc or not url or not expand.us_ok(j.get("location")):
                continue
            con.execute("INSERT OR IGNORE INTO descriptions VALUES (?,?,?,?)",
                        (url, name, (j.get("title") or "").strip(), zlib.compress(tidy(desc).encode("utf-8"), 6)))
            n += 1
    con.commit()
    con.execute("VACUUM")
    con.close()
    tmp.replace(path)
    print(f"{n} descriptions -> {path} ({path.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
