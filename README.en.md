# lora-audit

**Your training folder, finally readable.**

One command surfaces what nobody can see by looking at a `dataset/` folder: which images
have no caption, which captions are byte-identical, where the trigger word drifted, which
images are too small, what junk files slipped in.

No server, no database, no changes to your folder structure. The output is **a single HTML
file you double-click**.

[中文说明](README.md) · [MIT](LICENSE)

---

## Before / after

| Before | After |
|---|---|
| 47 images + 47 `.txt` files that all look alike | Every image's caption, source and size, at a glance |
| "I'm pretty sure everything is captioned" | `E001 图片没有 caption — 1` → tells you exactly which one |
| Training came out wrong, guessing it's the data | `W002 caption duplicated verbatim — 2` → the variable never made it into the caption |
| No idea what to fix | Every finding comes with a "what to do" line |

![audit report](docs/screenshot.png)

## Quickstart

```bash
# Not on PyPI yet — install from git for now,
pip install git+https://github.com/PolinniZhong/lora-audit.git

lora-audit scan ./dataset          # → ./dataset/_lora_audit/report.html
lora-audit scan ./dataset --open
```

Zero dependencies (Python 3.9+, standard library only). No manifest, no config file, no
requirement to reorganize your folder first.

## What it checks

| Rule | What it means |
|---|---|
| `E001` | Image has no caption (no sidecar `.txt`, no `default_caption.txt` fallback) |
| `W001` | Caption file exists but is empty |
| `W002` | Two or more per-image captions are byte-identical |
| `W003` | Trigger word is inconsistent (one face split across several tokens) |
| `W004` | Only `default_caption` fallback, no per-image variable |
| `W005` | Filename contains spaces / non-ASCII / unusual characters |
| `W006` | Caption file with no matching image (leftover from a rename or delete) |
| `W007` | Image is too small (short side < 512px) |
| `W008` | Mixed resolutions |
| `W009` | Dataset size outside the usual range (< 15 or > 150) |
| `W010` | OS junk files (`.DS_Store` / `Thumbs.db` …) |
| `W011` | `train.txt` / `val.txt` references files that don't exist |
| `W012` | Validation set isn't stratified (all from one group) |
| `W013` | File extension doesn't match the actual format (e.g. a WebP named `.png`) |

## Supported layouts

You don't reorganize anything — these are all understood:

```
dataset/                        dataset/                      dataset/
├── img001.png                  ├── img/                      ├── img/01_face/a.png + a.txt
├── img001.txt                  │   └── 01_face/a.png + a.txt  ├── cap_kohya/01_face/a.txt
└── img002.png (no caption)     └── default_caption.txt       └── default_caption.txt
   (kohya flat)                   (ai-toolkit / identity)         (dual profile)
```

Mirrored caption trees such as `cap_kohya/` are recognized as a second caption profile for
the same images rather than reported as orphans. kohya `10_name/` repeat folders, grouped
subdirectories and mixed layouts all work.

## "I meant to do that" (optional)

Some warnings are about things you did on purpose. Mixed resolutions, for instance — if you
configured **bucket training** deliberately, `W008` fires on every run and all you can do is
ignore it. For that, drop a `.lora-audit-ignore` in the dataset root:

```
# one rule ID per line; anything after # is the reason
W008 # square detail shots at 2048x2048 alongside 1773x2364 standard cells -- intentional bucketing
```

**Exempt is not hidden.** An exempted rule still shows up in the report — it is **downgraded to
"info" and labelled "exempted"**, with your reason printed verbatim, and the summary row shows
`已豁免 W008`. **We will not let a problem disappear silently; that is the one thing an audit
tool must never do.**

The file is **entirely optional**: without it, behaviour is exactly as before, and you never have
to learn a config format to use it.

## In CI

```bash
lora-audit scan ./dataset --json -        # machine-readable JSON on stdout
lora-audit scan ./dataset --strict        # warnings also fail the run
```

Exit codes: `0` clean · `1` problems found · `2` bad arguments or IO error.

## Documentation

| Document | What it answers |
|---|---|
| [docs/PRD.md](docs/PRD.md) ([English](docs/PRD.en.md)) | **What it is for, who it is for, what it will not do** — target user, core insight, the competitive gap, requirements and priorities, **non-goals**, risks and counterarguments |
| [docs/DESIGN.md](docs/DESIGN.md) ([English](docs/DESIGN.en.md)) | **Why it is built this way** — six hard constraints, 14 decisions (**including the rejected options and their costs**), module boundaries, what each verification layer **cannot** catch, known limitations |
| [CONTRIBUTING.md](CONTRIBUTING.md) | What kinds of rules and contributions get accepted (six criteria + worked examples both ways) |
| [CHANGELOG.md](CHANGELOG.md) | What changed |
| [docs/INSTANCES.md](docs/INSTANCES.md) | **Real-world usage log** — who found what on which data, and what changed as a result (**"it runs" is not an instance**) |

## Boundaries — what it will not do

- **It does not train.** It only reads; kohya / ai-toolkit / OneTrainer are untouched.
- **It does not upload.** No network requests at all; the report is fully offline
  (`lora-audit verify` enforces this as an invariant).
- **It does not modify your files.** Nothing moved, renamed or rewritten — it only adds an
  `_lora_audit/` directory.
- **It does not run a server.** No port, no database, no background process.
- **It does not do team collaboration, permissions or semantic search.** One person, one
  folder, one audit.

## Development

```bash
python3 -m unittest discover -s tests -v          # end-to-end tests (stdlib only)
python3 examples/make_example.py                  # synthetic dataset with known defects
lora-audit scan examples/demo-dataset --open

node tools/browser_check.mjs <report.html> --shot out.png   # real Chrome check
lora-audit verify <report.html>                             # output invariant check
```

`tools/browser_check.mjs` drives real Chrome over CDP to check rendering, the drawer, the
lightbox, filtering, search, theme switching and console errors. It is not optional:
`verify` cannot catch a JS error or a double-encoded path (both shipped here at least once),
and only a real browser can.

## License

MIT
