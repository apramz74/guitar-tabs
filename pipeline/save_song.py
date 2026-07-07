"""Save an extraction run as a song file the viewer can read.

Takes the extraction.json a pipeline run wrote to its debug dir, adds the
song's metadata (title, source, tuning, capo), and writes one song file to
data/songs/ in the PRD §6 shape. Also rebuilds data/songs/index.json — the
list the website reads to show the library (GitHub Pages can't list a
folder, so we keep the list as a file).

Example:
  .venv/bin/python pipeline/save_song.py <debug-dir>/extraction.json \
      --title "Cannock Chase" --artist "jmu.sikk" --capo 0
"""
import argparse
import json
import re
from pathlib import Path

SONGS_DIR = Path(__file__).resolve().parent.parent / "data" / "songs"


def slugify(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def rebuild_index():
    entries = []
    for p in sorted(SONGS_DIR.glob("*.json")):
        if p.name == "index.json":
            continue
        s = json.loads(p.read_text())
        entry = {
            "file": p.name,
            "title": s["title"],
            "artist": s.get("artist", ""),
            "capo": s.get("capo", 0),
            "measures": len(s["measures"]),
            "qa": s.get("qa", "draft"),
        }
        if s.get("archived"):
            entry["archived"] = True
        entries.append(entry)
    (SONGS_DIR / "index.json").write_text(json.dumps(entries, indent=2) + "\n")
    return entries


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("extraction", help="extraction.json from a pipeline run's debug dir")
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", default="")
    ap.add_argument("--source", default="", help="link or filename the song came from")
    ap.add_argument("--tuning", default="EADGBE")
    ap.add_argument("--capo", type=int, default=0)
    ap.add_argument("--qa", choices=["verified", "draft"], default="draft",
                    help="'verified' only after human QA against source frames")
    args = ap.parse_args()

    extraction = json.loads(Path(args.extraction).read_text())
    song = {
        "title": args.title,
        "artist": args.artist,
        "source": args.source,
        "tuning": args.tuning,
        "capo": args.capo,
        "qa": args.qa,
        "measures": extraction["measures"],
    }

    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    out = SONGS_DIR / f"{slugify(args.title)}.json"
    out.write_text(json.dumps(song, indent=2) + "\n")
    print(f"wrote {out} ({len(song['measures'])} measures, qa={args.qa})")

    entries = rebuild_index()
    print(f"index.json now lists {len(entries)} song(s)")


if __name__ == "__main__":
    main()
