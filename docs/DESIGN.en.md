# lora-audit Design Document (SDD) v0.1

> **Audience**: people who want to read the code, want to send a PR, or want to judge "whether this thing's engineering judgment holds up".
> **Not written here**: how to use it (see [README](../README.md)); what it is for, who it is for, and what it will not do (see [PRD](PRD.en.md)).
> Every number in this document is reproducible; commands are in §10.

**Architecture in one sentence**: turn a training folder into a **self-verifying read-only report** — a pure function, zero dependencies, the artifact is the application.

---

## 1. Six Non-Negotiable Constraints

Set the boundaries first, then look at the decisions — every item below appeared in the constraints; none of it is a retrospective summary.

| # | Constraint | How it is enforced |
|---|---|---|
| C1 | **Zero required dependencies** | `dependencies = []` in `pyproject.toml`, standard library only |
| C2 | **No server, no index, no database** | no port, no background process; `scan` is a single traversal |
| C3 | **Never modifies the input** | the whole repo has only **2** places that write files (`cli.py`'s report and the optional JSON), both under the path given by `-o` |
| C4 | **Offline self-contained artifact** | zero remote resources, zero `type="module"`, zero `fetch`/XHR |
| C5 | **The artifact is a single file** | CSS / JS / data all inlined; what the user gets is something that can be double-clicked and sent to someone |
| C6 | **User data is never treated as HTML** | only `textContent` / `createElement`, never string-concatenated `innerHTML` |

---

## 2. Decision Table: What Was Chosen, What Was Rejected, and What It Costs

The rejected options say more than the chosen ones.

| # | Decision | Rejected options | Why | Cost |
|---|---|---|---|---|
| D1 | The artifact is a **single self-contained HTML file** | an `index.html + css/ + js/` directory tree | what users want is something they can double-click, send over WeChat, drop into an issue; copy a directory tree and miss one file and you get a blank page | 47–63 KB artifact; changing styles requires regenerating |
| D2 | Images use **relative paths to the originals** | base64 inlining / build-time thumbnails | zero copying, instant output, works offline; inlining needs Pillow and bloats the artifact | the report **cannot be moved on its own** (`verify` reports it, the page degrades to "image cannot be read") |
| D3 | **Standard library only** | depend on Pillow (just to read width and height) | a user who only wants to `pip install` should not have to carry a C extension; auditing only needs file reads + regex + HTML output | maintain 5 image-header parsers in-house; **no thumbnail capability** |
| D4 | **Zero input contract**: reads no config file | require a manifest / declaration file | the community norm is "dump the images into a folder first"; requiring people to organize by our spec first is backwards | no way to know the user's "intent"; grouping can only be inferred from directory structure |
| D5 | **No server** | local server + live index | a static artifact is enough to answer "does this batch of images have problems"; turning it into a service kills "double-click to open" | no multi-user collaboration, no live updates, no semantic search (explicit non-goals) |
| D6 | **Write roughly 70 lines of lightbox** rather than inlining a third party | inline GLightbox (MIT) | its min file **has no license banner**; inlining it into a single-file artifact = an unattributed third-party minified blob in a public repo | fewer features (no gallery swiping/zoom), maintained in-house |
| D7 | `scan` **makes no judgment**, `rules` **never touches the filesystem** | judge while scanning | the rules become pure functions, unit-testable on their own — all 35 cases use synthetic fixtures and depend on no real image library | one extra data layer (`Dataset` / `ImageEntry`), one extra module |
| D8 | `verify` is a **separate subcommand** that only reads the artifact | stuff the checks into build | the artifact should be checkable by a third party; checking logic should not depend on generation logic | the two sides' schemas must stay in sync (pinned down by tests) |
| D9 | Rules **prefer under-reporting to false positives** | report as much as possible | once warnings are noisy, the user stops looking at them next time | may under-report on small datasets (see §6) |
| D10 | Theme switching is **not persisted** | write to `localStorage` | `localStorage` behavior under `file://` is inconsistent across browsers; a read-only page should not leave state behind | every open returns to dark mode |
| D11 | Large lists **do not** use `content-visibility: auto` | use it (the generic advice that "large lists need virtualization") | it interacts with `img loading="lazy"` to **serialize** parallel loading — measured at roughly a **10x** difference on a tile page like this (3.2s → 0.3s) | very large lists need another mechanism; currently covered by "only render in batches past 400 images" |
| D12 | Rule entries carry a **`kind`** (`image` / `file` / `none`) | just look at whether `items` has content | some rules' entries are **paths, not images** (junk files, orphan captions); using them to filter images yields only an empty grid | one more field in the payload, one more branch in the front end |
| D13 | Inline JSON escapes `</` → `<\/` | drop the JSON in directly | a caption can absolutely contain `</script>`, which would **truncate** the data block early | `verify` must decode it back once (implemented) |
| D14 | Add a `data:,` empty favicon | ignore it | for a `file://` page with no icon, Chrome requests `favicon.ico` and leaves an `ERR_FILE_NOT_FOUND` — that noise masks the problems actually worth seeing | none |

---

## 3. Module Boundaries

| Module | Lines | Responsibility | **Explicitly does not do** |
|---|---|---|---|
| `imagesize.py` | 178 | Read PNG/JPEG/GIF/BMP/WebP file headers to get width and height | does not decode pixels; **anything uncertain returns `None`, never raises** |
| `scan.py` | 352 | Walk the folder, faithfully record "what is here" | **makes no judgment, assigns no score**; writes no files |
| `rules.py` | 356 | Turn facts into findings | **never touches the filesystem** (input `Dataset`, output `list[Finding]`) |
| `report.py` | 183 | Render a single self-contained HTML | contains no business rules |
| `static/report.css` | 468 | Report page styles (token layer + components) | no hard-coded colors, only `--alc-*` tokens |
| `static/report.js` | 444 | Rendering, filtering, search, drawer, lightbox | no fetch, no remote requests, no `innerHTML` concatenation |
| `cli.py` | 235 | Arguments, exit codes, terminal summary, `verify` | contains no rules |
| `tests/test_smoke.py` | 342 | 20 end-to-end cases (incl. `--json -` stdout purity) | does not depend on pytest |
| `tests/test_layouts.py` | 216 | 15 **real-world layout** fixtures (kohya flat / `N_name` repeat dirs / ai-toolkit / `.caption` / meta files / mislabeled extensions) | downloads no third-party data |
| `tools/browser_check.mjs` | 315 | CDP-driven real Chrome, 15 assertion points | pulls in no third-party dependencies (uses Node's built-in WebSocket) |
| `examples/make_example.py` | 110 | Write PNGs with the standard library to build a dataset with known defects | does not depend on Pillow |

**The single most important boundary is D7**: precisely because `scan` makes no judgment and `rules` never touches the filesystem, the rules can be exhaustively tested — every "should report / should not report" assertion in the tests runs against synthetic fixtures in memory.

---

## 4. Data Flow

```
                  ┌──────────────────────────────────────────────┐
   dataset/ ─────►│ scan(root)                                   │  read-only, no judgment
   (user folder)  │  → Dataset{images[], meta[], orphans[], notes[]}
                  └──────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴────────────────┐
                    ▼                                ▼
        ┌───────────────────────┐      ┌──────────────────────────┐
        │ audit(ds) → [Finding] │      │ consensus_of(images)     │  pure functions, unit-testable
        │ 17 rules              │      │  → TriggerConsensus      │
        └───────────────────────┘      └──────────────────────────┘
                    │                                │
                    └───────────────┬────────────────┘
                                    ▼
                  ┌──────────────────────────────────────────────┐
                  │ build_payload(...)                           │  per-image relative src + findings lookup
                  └──────────────────────────────────────────────┘
                                    │
                                    ▼
                  ┌──────────────────────────────────────────────┐
                  │ render(...) → single-file HTML               │  CSS/JS/JSON inlined
                  └──────────────────────────────────────────────┘
                                    │
                                    ▼
                  ┌──────────────────────────────────────────────┐
                  │ verify(html) → invariant checks              │  separate subcommand, artifact only
                  └──────────────────────────────────────────────┘
```

The three caption sources for each image are the core distinction in this data model:

| `cap_source` | Meaning | Rule consequence |
|---|---|---|
| `sidecar` | a same-named `.txt` exists | normal; participates in the "duplicate" and "trigger-word drift" checks |
| `default` | inherits `default_caption.txt` | `W004`: identity block only, no per-image variable |
| `none` | neither exists | `E001`: during training it is either skipped or noise |

---

## 5. Invariants and Three Verification Layers

### 5.1 Checked Invariants

| # | Invariant | Guaranteed by | Automated |
|---|---|---|---|
| I1 | Artifact has zero remote resources | `lora-audit verify` | ✅ |
| I2 | Artifact has zero ES Modules (blocked by CORS under `file://`) | `verify` | ✅ |
| I3 | Artifact makes zero runtime requests (`fetch` / `XMLHttpRequest`) | `verify` | ✅ |
| I4 | The inlined data block is valid JSON, and every image is reachable by relative path | `verify` | ✅ |
| I5 | Zero console errors at script runtime | `browser_check` | ✅ (needs local Chrome) |
| I6 | Scan skips its own artifact directory `_lora_audit/` | unit test | ✅ |
| I7 | A clean dataset exits with code 0 (warnings are not noise) | unit test | ✅ |
| I8 | The whole repo has only 2 file-writing sites, both under the `-o` path | manual review | ⚠️ not automated |

### 5.2 The Three Verification Layers, and What Each **Cannot** Catch

| Layer | Command | Proves | **Cannot catch** |
|---|---|---|---|
| End-to-end | `python3 -m unittest discover -s tests` | rule hits, exit codes, URL encoding, mirrored caption trees | real rendering |
| Artifact invariants | `lora-audit verify <html>` | offline usability, data block validity, image reachability | **JS errors, double URL encoding**, layout |
| Real browser | `node tools/browser_check.mjs <html>` | rendering, drawer, lightbox, filtering, search, theme, console | rule correctness |

**This is not over-testing; this was learned the hard way.** This repository really did once miss a double URL encoding: the Python side called `quote()` once and the JS side called `encodeURI()` again, so a filename with a space became `%2520` → the browser reported `ERR_FILE_NOT_FOUND`. And `verify` **reported OK** — because it decodes only once, the path is still reachable. **Layer 2 structurally cannot catch layer 3's problems.** That is why `browser_check.mjs` is not optional.

The same lesson brings one more environment fact: on local Chrome 153, **renderer-domain commands do not return when connecting a page-level WebSocket directly** (the browser domain works fine); you must go through browser level + `Target.attachToTarget(flatten)` + `sessionId`. And its bundled renderer sandbox fails to start in restricted process environments (the symptom is "the connection is fine, events arrive, commands vanish into the void"), requiring `--no-sandbox`. Both are written in the script's header comments.

---

## 6. Rule Engine Tradeoffs

17 rules: **1 error / 13 warning / 3 info**.

### 6.1 Three Severity Levels

| Level | Meaning | Effect on exit code |
|---|---|---|
| `error` | training **will** go wrong (image has no caption) | makes the exit code 1 by default |
| `warn` | very likely a problem, but possibly intentional | only affects `--strict` |
| `info` | merely states an identified fact (layout, grouping, inferred trigger word) | no effect |

### 6.2 What "Prefer Under-Reporting to False Positives" Looks Like Concretely

| Practice | Example |
|---|---|
| **Stay silent below threshold** | `W003` trigger-word drift: samples < 3, or the dominant trigger word covering < 60%, **does not report** |
| **Concessive wording, no hard verdict** | `W008` inconsistent resolution writes "bucket training by nature wants variety, so if this is not intentional on your part…" |
| **Only report what can be verified at a glance** | no guessing intent, no judging art style, no deciding "whether this image is good" |
| **Separate facts from advice** | `scan` only records; judgment is concentrated in `rules`; every `warn`/`error` carries a "what to do" |

### 6.3 Two "Real World" Details of the Rules

**Mirrored caption tree** (things like `cap_kohya/`): a **second** set of captions for the same batch of images, which by nature has no same-named images. Judging "no same-named image → orphan" produces a screen full of false positives — on a real dataset the first run reported **47 orphans**. The current rule is "different path but same name → another caption profile", and it is stated in the report's "detected layout".

**Entry type `kind`**: the entries of `W006` (orphan caption) and `W010` (OS junk) are **paths, not images**. An early version rendered a "show only these N images" filter button for them too, which gave an empty grid when clicked.

---

## 7. Bugs Hit in Practice (All Fixed; Listed So They Are Not Repeated)

| # | Symptom | Root cause | Who could only find it |
|---|---|---|---|
| 1 | A real dataset reported 47 orphan captions | Treated the `cap_kohya/` mirrored tree as orphans | running it on a real folder |
| 2 | Filenames with spaces permanently broke images (`ERR_FILE_NOT_FOUND`) | double URL encoding (`%2520`) | **a real browser** (`verify` reported OK) |
| 3 | With 14 problems, the image section was pushed below 3000px | problem cards laid out in a single column | a real browser (measuring the first-image offset) |
| 4 | Path-type rules rendered an image-filter button that gave an empty grid | entry type not distinguished | a real browser (clicking it) |
| 5 | One `ERR_FILE_NOT_FOUND` noise entry in the console | `file://` page missing a favicon | a real browser (reading the console) |
| 6 | Check results not visible on the first screen / block text overlapping | hard-coded block heights + long text not shrinking | visual inspection after generation |
| 7 | **No image size was readable at all**, making `W007`/`W008` blind | the image parser was dispatched by **extension**, while the `.png` files in a real dataset were actually WebP | **running it on a real third-party dataset** |
| 8 | `lora-audit scan --json - \| jq` failed to parse | the human-readable summary and the JSON were both printed to stdout | trying to use the CI recipe the README itself recommends |

---

## 8. Known Defects and Costs (Honest List)

1. **Images load the originals; there is no thumbnail channel.** Datasets in the thousands will be slow on the first screen. The extras `pip install lora-audit[thumbs]` is already declared in `pyproject.toml`, but **the channel is not implemented**.
2. **The report cannot be moved on its own.** Images use relative paths, so the report and the dataset must keep their relative positions; once moved, `verify` reports it and the page degrades to "image cannot be read (moved or deleted)".
3. **Exemption works per-rule, not per-image.** That `W008` noise is now solved by the optional `.lora-audit-ignore` (exempt is not hidden: downgraded to info, labelled, reason printed verbatim — see [INSTANCES](INSTANCES.md) instance 01); but exempting "just these three images" is still not possible — you can only exempt a whole rule.
4. **Only images are audited.** Video, audio, and any non-image asset are outside the scan.
5. **Trigger-word detection is conservative**: it takes only the first word of the caption; it needs ≥3 images and ≥60% coverage before it dares report drift; multiple trigger words are not supported.
6. **`W012` (val not stratified) is only meaningful when the dataset ships its own `val.txt`**; with no manifest it says nothing at all.
7. **The batch-rendering threshold (>400 images) is a guess**, with no measured basis.
8. **Validated on exactly one real third-party public dataset** (9 images, zero captions, `.png` files that were actually WebP), plus 15 layout fixtures built from the trainers' documented conventions. It has **not** yet faced a large number of real directories — if the folder you have scans wrong, open an issue: the [template](../.github/ISSUE_TEMPLATE/bug-report.yml) asks for a directory tree + the raw caption text, not images.

---

## 9. Not Yet Done, and Trigger Conditions

| Item | Trigger condition |
|---|---|
| `--thumbs` thumbnail channel (needs Pillow) | a user reports "thousands of images is too slow" |
| manifest support (an optional gate progress bar) | the user **already has** a manifest, rather than being asked to write one |
| English UI | English-speaking users report the UI is unreadable; the current UI copy is Chinese |
| multiple trigger words / caption prefix templates | a real use case appears |
| video / audio auditing | **not doing it** — that is a different tool |

---

## 10. How to Verify That Everything in This Document Is True

```bash
git clone <repo> && cd lora-audit

python3 -m unittest discover -s tests -v     # 35 cases (standard library only)
python3 examples/make_example.py             # build a dataset with 6 known defect classes
python3 -m lora_audit scan examples/demo-dataset --open
python3 -m lora_audit verify examples/demo-dataset/_lora_audit/report.html

node tools/browser_check.mjs examples/demo-dataset/_lora_audit/report.html --shot out.png
```

The last one needs Chrome/Chromium on the machine; without it, it is **skipped** (exit code 0), so it does not become a barrier for contributors.

---

## 11. Version History

- **v0.1 (2026-09-20)** First version, corresponding to `lora-audit 0.1.0`. Contains the six constraints, 14 decisions (including rejected options), module boundaries, the three-layer verification strategy, and the list of known defects.
