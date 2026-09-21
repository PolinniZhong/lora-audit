# lora-audit Product Requirements Document (PRD) v0.1

> **Audience**: people who want to know "what problem does this solve, who is it for, why does it look like this, and what does it not do".
> **This document answers "what do we want"**; how it is built is in the [design document](DESIGN.en.md), how to use it is in the [README](../README.md), what changed is in the [CHANGELOG](../CHANGELOG.md).
> **Basis**: a complete landscape-and-differentiation study (including per-project star / license / last-commit measurements, all as of 2026-09-20). **Data that expires stays on the research side; this document keeps only the conclusions** — star counts go stale in a few weeks, and product judgment should not rot along with them.

---

## 0. One-Pager

| Item | Conclusion |
|---|---|
| **Definition in one sentence** | Run a **read-only audit** over an existing LoRA training folder: no server to start, no changes to your directory layout, producing one report a person can double-click open. |
| **Target users** | People in a one-person / small-team setting who **train their own LoRA**: they have one `dataset/` folder, tens to hundreds of images, and a pile of same-name `.txt` files. |
| **Core insight** | Training engines (write), model managers (distribution), and caption editors (write) all have someone building them; **the read-only view — "what does this batch of images actually look like, are captions missing, did the trigger word drift" — is zero.** |
| **MVP boundary** | **Does**: scan one existing folder → emit a read-only report. **Does not**: training, server, database, desktop app, collaboration, permissions, semantic search, video or audio. |
| **Success criterion** | Not star counts. It is **whether a user, after their first run, can point at at least one problem they did not know about before**. |

---

## 1. The Problem

### 1.1 Who Is Hurting

People who train their own character LoRAs. Their workflow looks like this: collect images → caption them → throw them into kohya / ai-toolkit → train → the result is wrong → **go back and guess whether it is a data problem**.

### 1.2 Where It Hurts (three concrete scenarios, all real)

1. **"I'm pretty sure I captioned them all."** Dozens of images plus dozens of `.txt` files, all with look-alike filenames; nobody checks them one by one. One missing image, one empty file, a trigger word mistyped on a single image — **invisible to the naked eye**, but they genuinely eat into training results.
2. **The variable never made it into the caption.** Two different images with byte-identical captions (left over from copy-paste) tells the model "these two are the same". This class of problem **only shows up when you put the captions side by side**.
3. **When the result is wrong there is no way to attribute it.** The dataset was collected two months ago and edited in several rounds since; **nobody knows anymore where the current batch of images came from**.

### 1.3 Why Now

- The training side has gone mainstream (kohya_ss / ai-toolkit are both ten-thousand-star projects); **it is only once many people use them that "what is actually in the data" becomes a question**;
- but the ecosystem's attention is entirely on "how to train better" (parameters, base models, samplers), and **the data-side tooling is stuck at single-machine widgets for "look at an image, edit its tag"**;
- existing solutions are either **enterprise DAM that must run as a service** (too heavy for an individual) or a **generic photo album** (stuck at the "viewing images" layer, with no production semantics).

---

## 2. Competition and the Gap

### 2.1 Five Kinds of Adjacent Solutions, and Why None of Them Solves This Problem

| Category | What they do | Why they are not a competitor |
|---|---|---|
| Generic open-source DAM / MAM | ingestion → index → search / publish | **every status word is a consumption state** (backed up / favorited / archived / published); not one treats "which production step has this asset passed" as a first-class concept; and all of them require a service + a database |
| SD / ComfyUI / LoRA training ecosystem | generate images, train, install nodes, download models | training engines only understand "image + same-name txt", model managers only understand `.safetensors`. **The write side has builders; the read side is zero** |
| Training-dataset visualization libraries | pick dirty data out of hundreds of annotations before training | Python libraries / notebook workflows aimed at ML engineers, **not an asset view for creators**, and they do not answer "where did this dataset come from" |
| Static / offline galleries | scan a directory → generate a backend-free static album | the approach is right, but they **stop at the "generic photo album" layer**, with no AIGC production semantics |
| Agent Skill ecosystem | character-consistency **generation** techniques (prompt methodology) | teaches you how to draw consistently, **not an asset ledger**: no cross-library cataloging, no stage-gate tracking, no deterministic training-set output |

### 2.2 Capabilities We Claim, and Who Has or Has Not Built Them

| Capability | Generic DAM | Training ecosystem | Static gallery | Agent Skill | Verdict |
|---|---|---|---|---|---|
| A shared contract across multiple asset libraries (stable ID + content-fingerprint reverse lookup) | ❌ | ❌ each project's conventions are mutually incompatible | ❌ | ❌ | **genuine gap** |
| Stage gates / SOP as a reconcilable process flow | ❌ approval flows, but no process flow | ❌ the SOP only ever lives in a blog post | ❌ | ❌ | **genuine gap** |
| Deterministic training-set output + dual caption profiles + stratified validation set + hash audit | ❌ | ❌ auto-captioning emits a single caption only | ❌ | ❌ | **the hardest differentiation** |
| Purely static, offline, read-only, double-click to open | ❌ every one needs a service + a database | ❌ every one needs a process / the cloud | ✅ someone has made this work | ❌ | **table stakes** |

### 2.3 The Key Call: Separate Real Differentiation from Table Stakes

This call determines the product's **external story**:

- **Real differentiation** (others cannot do it or have not done it): deterministic training-set production and auditing; the middle gap of "a pile on the write side, zero on the read side"; the folder is the contract (the data is already in the folder, the tool only generates a read-only snapshot).
- **Table stakes, not a selling point**: purely static / double-click to open over `file://`. Someone has already made this path work; it only **gets you in the door**, it is not a reason for anyone to pick you. **It does not go into the product's headline pitch.**
- **Self-indulgent differentiation** (others do not do it only because it does not matter, or because we overestimated how general it is): design tokens / shadow elevation / image-viewer components; architectural payoffs like "zero code to add a new library" (a single user has one library, so it is of no use to them); **and our own complete methodology (multi-stage-gate SOP, cross-library asset contract, an integrated browsing front end) — too heavy as a default shape**.

**These three categories directly determine the MVP boundary** (§3.3).

---

## 3. Product Definition

### 3.1 In One Sentence

**Given an existing training folder, automatically generate a read-only static report that lays out the data problems "the human eye cannot see".**

### 3.2 Input and Output (the strict definition of "zero contract")

| | Requirement |
|---|---|
| **Input** | One ordinary folder. **No** manifest, declaration file, config file, database, or naming convention is required. The directory structure you already have is the input. |
| **Output** | **A single self-contained HTML file**, double-click to open, usable offline (zero remote resources / zero ES Modules / zero runtime requests). |
| **Side effects** | **Exactly one extra `_lora_audit/` directory.** No moving, renaming, or rewriting of any file in the dataset. |

Zero contract is a **product requirement**, not implementation fastidiousness: the adjacent ecosystem's default assumption is "start a service first, put the data in a database", while the real user is "**dump the images into a folder first, then figure out how to rescue it**". Asking them to organize by our spec first points the wrong way.

### 3.3 Non-Goals (hard-coded; "I'll just do it on the side" is not accepted)

- Training capability (read-only on data; kohya / ai-toolkit / OneTrainer are not touched)
- A local server / database / desktop app / Docker image
- Team collaboration, permission control, semantic search, live editing
- Video and audio
- Any feature that needs the network (including "just look up this model while I'm here")
- Making our own complete methodology the default: **stage-gate SOP, cross-library asset contract, and integrated browsing front end all stay out of the MVP**

> Rationale in §2.3 — every item is "others do not do it because it does not matter, or we overestimated how general it is". Cut them and the MVP is down to one thing.

---

## 4. Requirements

### 4.1 Functional Requirements

The status column corresponds to the released `0.1.0`.

| # | Requirement | Priority | Acceptance criteria | Status |
|---|---|---|---|---|
| FR-1 | Take one folder, emit a **single-file** report | P0 | the artifact can be opened on its own; `verify` passes the three offline invariants | ✅ |
| FR-2 | Detect **missing captions** | P0 | points at the specific file; distinguishes "no same-name txt" from "a `default_caption` fallback exists" | ✅ `E001`/`W004` |
| FR-3 | Detect **empty caption files** | P0 | an empty file is more insidious than a missing one and must be reported separately | ✅ `W001` |
| FR-4 | Detect **duplicate per-image captions** | P0 | reports the duplicate group and a snippet of the original text | ✅ `W002` |
| FR-5 | Extract the **trigger word** and report **inconsistency** | P0 | infers the dominant trigger word; stays **silent** when the evidence is insufficient (≥3 images and ≥60% coverage) | ✅ `W003` |
| FR-6 | Detect **orphan captions** (a txt with no image) | P1 | not falsely triggered by a "mirrored caption directory" | ✅ `W006` |
| FR-7 | Detect **filenames / resolution / scale / junk files / dead manifest links / unstratified val** | P1 | none of them produces a false positive; mixed resolutions must come with hedged wording | ✅ `W005`/`W007`–`W012` |
| FR-8 | Detect **an extension that does not match the actual format** | P2 | decided by file header, not by extension | ✅ `W013` |
| FR-9 | **Every finding carries a "what to do" line** | P0 | a warning with no way out does not appear | ✅ |
| FR-10 | Support the multiple layouts that actually exist | P0 | kohya flat / `N_name` repeat directories / ai-toolkit (`img/` + `default_caption.txt`) / dual caption profiles / grouped by subdirectory / mixed | ✅ |
| FR-11 | The report **can filter, search, view images full size, and copy captions** | P1 | each one verified in a real browser | ✅ |
| FR-12 | **Machine-readable output**, CI-friendly | P1 | `--json -` writes **pure JSON** to stdout (the summary goes to stderr); `--strict` makes warnings affect the exit code too | ✅ |
| FR-13 | Artifact **invariant self-check** | P0 | `verify` checks the artifact independently (it does not depend on the generation logic) | ✅ |
| FR-14 | Thumbnail channel (first-screen performance on large datasets) | P1 | first screen usable at thousands of images; needs an imaging library | ❌ not implemented |
| FR-15 | manifest support (an optional gate progress bar) | P2 | **only enabled when the user already has a manifest**; they are not asked to write one | ❌ not implemented |
| FR-16 | English UI | P2 | i18n the copy | ❌ not implemented (the UI copy is currently Chinese) |

### 4.2 UX Requirements

| # | Requirement | Rationale |
|---|---|---|
| UX-1 | **Zero required dependencies**, installed in one `pip install` | carrying a C extension just to read a width and height is a bad trade; auditing only needs file reads + regex + HTML output |
| UX-2 | First report within 30 seconds | no index, no service, no full-disk scan |
| UX-3 | Findings appear on the first screen **before the images** | users come to investigate problems, not to browse an album |
| UX-4 | **No documentation to read** on first run | one command; the report explains itself |
| UX-5 | Warnings **prefer under-reporting to false positives** | once noise appears, the user stops looking next time |

### 4.3 Rule Admission Criteria

A new rule must satisfy all six at once (R1 verifiable at a glance / R2 does not guess intent / R3 has a clear way out / R4 prefers under-reporting to false positives / R5 introduces no required dependency / R6 does not modify the input); details and **concrete examples of rules that pass and rules that fail** are in [CONTRIBUTING](../CONTRIBUTING.md) §2.

> In one line: **any rule that needs to read image content, call a model, or "get a feel for it" is not accepted.**

---

## 5. Success Criteria

**Star counts are explicitly not a criterion.** Three observable ones:

1. **Usefulness**: after the first run, the user can name at least one problem they did not know about before. (If that does not happen, the product does not hold up — this is the most important one.)
2. **Being cited**: someone wires it into their own workflow — CI, a passing mention in a ComfyUI tutorial, an audit screenshot attached to a model release page.
3. **Reproducible**: the "directory tree + raw caption text" given in an issue reliably reproduces the same result. That proves the behavior is predictable rather than mystical.

**Expected scale**: a **useful small tool** (on the order of a few hundred stars), not a hit. That follows from "this niche is a genuine gap, but nobody is complaining about the pain" (§6); it is not modesty.

---

## 6. Risks and Counterarguments (which must be faced)

| # | Risk | Response |
|---|---|---|
| 1 | **Nobody is complaining about this pain.** Search the whole community and there is no hit post saying "I need a tool to manage my training assets" — the pain is real, but it is treated as "a matter for my own hard drive" and never rises to a product requirement | so **the first 100 stars will be very hard to get**; the MVP has to prove "one glance shows you problems you cannot see yourself", not "I will organize your assets very neatly for you" |
| 2 | **The community may genuinely want nothing more than "a folder + one Excel sheet"** | if so, our value proposition does not hold. That is exactly why the first criterion in §5 exists |
| 3 | **The maintainer's curse**: in this niche, the ones that survive are individual maintainers | position it explicitly as "validating a methodology" rather than "a long-term maintained product"; neither the README nor this document promises a roadmap |
| 4 | **The ceiling of the static approach**: it cannot do multi-person collaboration / live editing / permissions | **say "not solved" out loud**, and hard-code it as a non-goal in the docs (§3.3) |
| 5 | **"Zero code to add a new library" does not travel**: 99% of users have exactly one library | it does not go into the external story (§2.3) |
| 6 | **Our own methodology carries the highest self-indulgence risk** | avoided through the MVP boundary: the whole methodology stays out of the MVP; only "the folder is the contract" remains, the one principle that genuinely benefits the user |

---

## 7. Delivered vs Not Delivered (an honest `0.1.0` accounting)

**Delivered**: all of FR-1 through FR-13; 17 rules; 4 real layouts + the mirrored caption directory; the single-file offline report; two layers of verification (`verify` + real-browser testing).

**Not delivered**: FR-14 thumbnail channel, FR-15 manifest, FR-16 English UI (trigger conditions in §8).

**How far it has been verified (this column must be honest)**:
- synthetic fixtures covering 7 known defect classes;
- 15 layout fixtures built from the trainers' **documented conventions**;
- **1 real third-party public dataset** (9 images, zero captions, `.png` files that were actually WebP) — that one run is what surfaced the two problems synthetic fixtures could not find: "the parser dispatched by extension" and "`--json` stdout was polluted";
- **it has not yet faced a large number of real directories.**

---

## 8. Trigger Conditions: When to Reconsider

| Item | Trigger condition |
|---|---|
| `--thumbs` thumbnail channel (would introduce an imaging library) | a user reports "thousands of images is too slow" |
| manifest support (an optional gate progress bar) | the user **already has** a manifest, rather than being asked to write one |
| English UI | English-speaking users report the UI is unreadable |
| Multiple trigger words / caption templates | a real use case appears |
| Video / audio | **not doing it** — that is a different tool |

---

## 9. How This Document Relates to the Others

```
README.md          how to use                     (users)
   ↓
docs/PRD.md        what we want, for whom, what we will not do  ← this document
   ↓
docs/DESIGN.md     how it is built, why that way, what it costs
   ↓
CONTRIBUTING.md    what contributions get accepted
CHANGELOG.md       what changed
   ↓
research side (not distributed with the repo)  evidence: per-project measurements, the original decision process
```

**The PRD is the decision layer; the research is the evidence layer.** The two do not overlap: this document only writes down "what was decided", the research owns "what justifies deciding that".

---

## Version History

- **v0.1 (2026-09-20)** First version, corresponding to `lora-audit 0.1.0`. Distilled from a complete landscape-and-differentiation study: it keeps every product judgment (where the gap is, real differentiation vs table stakes, the six risks) and drops the data that expires (per-project stars / licenses / recent commits) and internal structural information.
