# campfire-music

Songs, covers, the playlist and the banner slides for the **Campfire** world in Banter.
The world loads everything from here at runtime (GitHub Pages), so adding a song needs **no world rebuild**.

Base URL (after enabling Pages): `https://ladypoly.github.io/campfire-music/`

## Structure

| Path | What |
|---|---|
| `playlist.json` | The song list the banner player reads |
| `slides.json` | Tips / featured worlds shown on the banner while no music plays |
| `tracks/` | Audio files (`.ogg` preferred, `.mp3` ok) |
| `covers/` | Square cover images, one per track |
| `slides/` | Slide images |
| `CREDITS.md` | Artist + licence for every track (keep in sync with the playlist) |

## Add a song

1. Put the audio in `tracks/` — **file name = track id**, lower case, no spaces: `tracks/fireside-waltz.ogg`
2. Put the cover in `covers/` with the same id: `covers/fireside-waltz.jpg`
3. Add an entry to `playlist.json` (copy an existing one), set `"enabled": true`
4. Add the credit line to `CREDITS.md`
5. Commit to `main` — Pages updates within ~1 minute; the world picks it up on the next load

### File specs (Quest friendly)

- **Audio:** Ogg Vorbis ~128 kbps (or MP3 128–160 kbps), 44.1 kHz stereo, peak-normalised to about −1 dB, ideally loudness-matched (≈ −14 LUFS) so the volume doesn't jump between songs. ~4 MB per 4-minute song. Single files must stay under 100 MB (GitHub limit).
- **Cover:** JPG, 512 × 512, under ~150 KB.
- **Slide image:** JPG, 1024 × 512 (2:1, the banner shape), under ~250 KB.

### Licences

Only add music you may share publicly: your own, or Creative Commons / royalty-free tracks whose licence allows streaming in a public space.
`CC BY` / `CC BY-SA` are easiest (credit is shown on the banner). Avoid `ND`/`NC` unless you have checked it fits.
**No** remixes / edits of commercial songs.

## playlist.json fields

| Field | Meaning |
|---|---|
| `id` | Unique, = file names in `tracks/` and `covers/` |
| `title`, `artist` | Shown on the banner |
| `file`, `cover` | Paths relative to the base URL (or full `https://` URLs) |
| `duration` | Length in seconds — used to keep everyone in sync before the file has loaded |
| `license`, `source` | Credit shown on the banner / in CREDITS.md |
| `enabled` | `false` = skipped by the player (handy for drafts) |

## Limits (GitHub Pages)

Site ≤ 1 GB (≈ 200 songs), soft limit 100 GB traffic / month (≈ 25 000 song plays).
If we outgrow it, the files move to another host (e.g. Cloudflare R2) and only `baseUrl` changes.
