# tests/fixtures/

Sample images used by `scripts/seed.py` to populate idol profile photos and product
cover art through the real upload/storage pipeline (`get_storage().save()`,
the same coroutine `app/router/idol.py` and `app/router/products.py` call on
a real multipart upload — see `upload_fixture()` in `scripts/seed.py`).

## What these are

**Procedural placeholder art, not real character art.** No AI image
generation tool was available in the environment this project was built in
(no native tool, no MCP connector, no skill covered it — confirmed before
falling back to this approach). Every image here is generated deterministically
with Pillow: a two-color gradient (linear or radial) colorized from the idol's
or release's `idol_colors` hex code, a geometric pattern overlay (dots,
diagonal stripes, a grid, concentric rings, or spikes — picked
deterministically per subject), and a monogram or title rendered in
Poppins/Big Shoulders Display. They're good enough to exercise the storage
abstraction end to end — upload, content-type handling, URL generation,
serving — but they are intentionally abstract and make no attempt to depict
a character.

## Layout

- `idols/<slug>.png` — one 512×512 portrait per idol, named by a slugified
  version of their full name (e.g. `hinata-kisaragi.png`). 25 files.
- `products/<slug>.png` — one cover per album/single/EP (600×600) or
  lightstick (320×720, with an added glow blur), named by the product's
  slug as it appears in `scripts/seed.py`'s `releases` / `lightsticks` lists
  (e.g. `sakura-prism-hanabi-ranman.png`, `sakura-prism-lightstick.png`).
  18 files.

Every filename `scripts/seed.py` requests via `upload_fixture()` is generated from
the same slugification rule the generation script uses, so the two stay in
sync as long as both are edited together.

## Regenerating

The generation script (`gen_fixtures.py`, kept alongside this README) is a
standalone Pillow script with no dependency on the app itself — it can be
re-run any time to regenerate the full set, e.g. after changing an idol's
color or adding a new release:

```bash
pip install pillow  # already a project dependency; only needed standalone
python3 gen_fixtures.py
```

It writes into `tests/fixtures/{idols,products}/`, overwriting existing
files with the same name. The idol/release/lightstick rosters are hardcoded
at the top of the script (`IDOLS`, `RELEASES`, `LIGHTSTICKS`) and must be
kept in sync with the corresponding lists in `scripts/seed.py` — same names, same
slugs, same hex codes — since that's what keeps the placeholder art color-
themed consistently with what's actually stored in the database.

## Swapping in real art later

Because every image is pushed through `get_storage().save()` rather than a
hardcoded `image_url`, replacing a placeholder with real character art later
is just a matter of dropping a same-named (or differently-named, with a
one-line change in `scripts/seed.py`) file into `idols/` or `products/` and
re-running `scripts/seed.py` against a fresh database — no code changes needed
beyond that.
