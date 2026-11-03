"""Campfire Radio - build the GitHub Pages site the world loads.

    python scripts/build.py [--month 2026-12] [--out _site]

- Playlist = months/<month>.txt (default: this month, UTC; falls back to the newest older month, or to own.txt only)
  + your own songs from own.txt, spread evenly through the mix: all songs tagged for this month, all songs added this
  month (column 'added'), and if that is fewer than own_songs (seasons.json) some all-year songs (a different set each month).
  Runs on every push, so a song you add mid-month is in the playlist a few minutes later (the world re-reads it every 5 min).
- Every song is downloaded once (cache in .cache/), loudness-matched (-14 LUFS, peaks -1.5 dB), converted to
  Ogg Vorbis 44.1 kHz -> tracks/<id>.ogg; cover -> covers/<id>.jpg 512x512 (missing cover -> one is drawn).
- The previous month's files stay online too, so people who are in the world at midnight on the 1st keep listening.
- Writes playlist.txt (what the jukebox reads: id | title | artist | m:ss | licence) and CREDITS.md.
A song that can't be downloaded / converted is skipped (logged), the rest still goes out.
"""
import argparse
import datetime as dt
import glob
import hashlib
import os
import random
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

STATIC = [".nojekyll", "README.md", "slides.json", "slides"]


def month_file(month):
    if os.path.exists(C.path("months", f"{month}.txt")):
        return month
    older = sorted(os.path.basename(f)[:7] for f in glob.glob(C.path("months", "????-??.txt")) if os.path.basename(f)[:7] <= month)
    return older[-1] if older else None


def prev_month(month):
    y, m = map(int, month.split("-")); k = y * 12 + m - 2
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(" ".join(cmd[:3]) + "...: " + r.stderr[-400:])
    return r.stdout


USED = set()   # cache files used in this run (the rest is deleted at the end so the cache does not grow forever)


def fetch(src, cache):
    """local repo path or URL -> local file"""
    if not src.startswith("http"):
        p = C.path(src)
        if not os.path.exists(p):
            raise FileNotFoundError(src)
        return p
    ext = os.path.splitext(src.split("?")[0])[1][:6] or ".bin"
    dest = os.path.join(cache, "src", hashlib.sha1(src.encode()).hexdigest()[:16] + ext)
    if not os.path.exists(dest):
        C.download(src, dest)
    USED.add(os.path.abspath(dest))
    return dest


def duration(f):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", f])
    return float(out.strip() or 0)


def make_audio(song, cache, out_dir):
    dest = os.path.join(out_dir, "tracks", song["id"] + ".ogg")
    src = fetch(song["audio"], cache)
    key = hashlib.sha1((song["audio"] + str(os.path.getsize(src)) + "v1").encode()).hexdigest()[:16]
    cached = os.path.join(cache, "ogg", key + ".ogg")
    if not os.path.exists(cached):
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-map_metadata", "-1",
             "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "2",
             "-c:a", "libvorbis", "-q:a", "4", cached])
    USED.add(os.path.abspath(cached))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(cached, dest)
    return duration(dest)


def draw_cover(song, dest, theme):
    from PIL import Image, ImageDraw, ImageFont
    h = int(hashlib.sha1(song["id"].encode()).hexdigest()[:6], 16)
    palettes = {"12": [(150, 30, 30), (20, 90, 50)], "10": [(60, 20, 70), (220, 110, 20)], "01": [(40, 70, 120), (200, 220, 240)],
                "02": [(120, 30, 60), (240, 170, 180)]}
    a, b = palettes.get(theme, [(120, 58, 24), (232, 112, 36)])
    img = Image.new("RGB", (512, 512))
    d = ImageDraw.Draw(img)
    for y in range(512):
        t = y / 511
        d.line([(0, y), (512, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    for k in range(6):   # a few soft embers
        x, y, r = (h >> (k * 3)) % 512, (h >> (k * 2 + 5)) % 512, 20 + (h >> k) % 60
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 230, 190), width=3)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    words, lines, cur = song["title"].split(), [], ""
    for w in words:
        if len(cur + " " + w) > 16 and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    y = 256 - len(lines[:4]) * 28
    for line in lines[:4]:
        d.text((256, y), line, fill=(255, 246, 225), font=font, anchor="ma"); y += 56
    img.save(dest, quality=88)


def make_cover(song, cache, out_dir, theme):
    dest = os.path.join(out_dir, "covers", song["id"] + ".jpg")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if song.get("cover"):
        try:
            src = fetch(song["cover"], cache)
            run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", "scale=512:512:force_original_aspect_ratio=increase,crop=512:512",
                 "-frames:v", "1", "-q:v", "4", dest])
            return
        except Exception as e:
            print(f"  cover {song['id']}: {e} -> drawn cover")
    draw_cover(song, dest, theme)


def own_for(month, n_min):
    mm = month[5:7]
    own = C.own_songs()
    tagged = [o for o in own if mm in o["months"]]
    new = [o for o in own if o["added"][:7] == month and o not in tagged and (not o["months"] or mm in o["months"])]
    allyear = [o for o in own if not o["months"] and o not in new]
    allyear.sort(key=lambda o: hashlib.sha1((month + o["id"]).encode()).hexdigest())   # a different set each month, stable within it
    chosen = tagged + new
    chosen += allyear[: max(0, n_min - len(chosen))]
    return [{"id": o["id"], "title": o["title"], "artist": o["artist"], "length": "", "licence": o["licence"],
             "page": "own", "audio": o["audio"], "cover": o["cover"]} for o in chosen]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=os.environ.get("MONTH") or dt.datetime.utcnow().strftime("%Y-%m"))
    ap.add_argument("--out", default=C.path("_site"))
    ap.add_argument("--cache", default=C.path(".cache"))
    args = ap.parse_args()
    out, cache = args.out, args.cache
    shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
    for s in STATIC:
        p = C.path(s)
        if os.path.isdir(p): shutil.copytree(p, os.path.join(out, s))
        elif os.path.exists(p): shutil.copy(p, os.path.join(out, s))

    cur = month_file(args.month)
    if cur:
        songs, title = C.read_manifest(f"months/{cur}.txt")
        have = {s["id"] for s in songs}
        own = [o for o in own_for(args.month, C.load_json("seasons.json").get("own_songs", 5)) if o["id"] not in have]
        for i, o in enumerate(own):     # spread evenly through the mix
            pos = round((i + 0.5) * (len(songs) + len(own)) / len(own))
            songs.insert(min(pos, len(songs)), o)
        print(f"== playlist {cur}: {title} ({len(songs) - len(own)} found + {len(own)} own songs)")
    else:   # no monthly playlist yet -> only the own songs
        songs = [{"id": o["id"], "title": o["title"], "artist": o["artist"], "length": "", "licence": o["licence"],
                  "page": "own", "audio": o["audio"], "cover": o["cover"]} for o in C.own_songs()]
        title = "Campfire Radio"
        print(f"== no months/*.txt yet -> {len(songs)} own songs")
    theme = (cur or args.month)[5:7]

    lines, credits, done = [], [], set()
    for s in songs:
        if s["id"] in done:
            continue
        try:
            secs = make_audio(s, cache, out)
            make_cover(s, cache, out, theme)
        except Exception as e:
            print(f"! skipped {s['id']}: {e}")
            continue
        done.add(s["id"])
        lines.append(" | ".join(C.clean(x) for x in (s["id"], s["title"], s["artist"], C.mmss(secs), s["licence"])))
        src = "own song" if s["page"] == "own" else f"[source]({s['page'] or s['audio']})"
        credits.append(f"| {C.clean(s['title'])} | {C.clean(s['artist'])} | {s['licence']} | {src} |")
        print(f"  ok  {s['id']}  {C.mmss(secs)}")

    # last month's files stay reachable for listeners who joined before the switch
    if cur:
        prev, _ = C.read_manifest(f"months/{prev_month(cur)}.txt")
        for s in prev:
            if s["id"] in done: continue
            try:
                make_audio(s, cache, out); make_cover(s, cache, out, theme)
            except Exception as e:
                print(f"  (previous month {s['id']} not kept: {e})")

    with open(os.path.join(out, "playlist.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {title if title.startswith('Campfire Radio') else 'Campfire Radio - ' + title}\n# id | title | artist | m:ss | licence   (built {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC from months/{cur or '-'}.txt)\n")
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(out, "CREDITS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Credits - {title}\n\nEvery song played in the Campfire world this month.\n\n| Song | Artist | Licence | Source |\n|---|---|---|---|\n")
        f.write("\n".join(credits) + "\n")
    for dp, _, fns in os.walk(cache):
        for fn in fns:
            if os.path.abspath(os.path.join(dp, fn)) not in USED:
                os.remove(os.path.join(dp, fn))
    size = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _, fns in os.walk(out) for fn in fns)
    print(f"== site: {len(lines)} songs in playlist.txt, {size / 1e6:.0f} MB")
    if not lines:
        sys.exit("no song could be built")


if __name__ == "__main__":
    main()
