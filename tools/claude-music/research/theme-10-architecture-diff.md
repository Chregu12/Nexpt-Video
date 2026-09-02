# Theme 10 — Competitive Skill Architecture Diff

**Research date**: 2026-04-16
**Scope**: Compare `claude-music` against 4 reference skills to identify architectural gaps and lift patterns.

---

## Repos surveyed (all cloned under `~/Desktop/Claude-music/research/scratch/`)

| Repo | Role | Source |
|---|---|---|
| `claude-music` (ours) | Subject of refactor | `~/Desktop/Claude-music/` |
| `acestep` (the ACE-Step team's Claude Code skill) | Domain competitor — research plan called this "the single most important competitive artifact" | `/home/agricidaniel/Desktop/Local-AI-Models/ACE-Step-1.5/.claude/skills/acestep/` |
| `claude-seo` (AgriciDaniel) | Architectural sibling — same author, same `skills/<feature>/SKILL.md` pattern | `github.com/AgriciDaniel/claude-seo` |
| `claude-blog` (AgriciDaniel) | Architectural sibling w/ tests | `github.com/AgriciDaniel/claude-blog` |
| `bitwize-music-studio/claude-ai-music-skills` | Music-domain competitor — 52 skills, bundled MCP server | `github.com/bitwize-music-studio/claude-ai-music-skills` |
| `anthropics/skills` | Official exemplars | `github.com/anthropics/skills` |

---

## 1. High-level comparison matrix

| Dimension | **claude-music** (ours) | **ace-step-skills** | **claude-seo** | **claude-blog** | **bitwize** | **anthropic/skill-creator** |
|---|---|---|---|---|---|---|
| **Orchestrator style** | Main `claude-music/SKILL.md` routes to flat sibling sub-skills via Read | Single monolithic SKILL.md wraps 1 bash script | `skills/seo/SKILL.md` as main orchestrator + `skills/seo-*/` sub-skills | `skills/blog/SKILL.md` orchestrator + `skills/blog-*/` siblings | Flat peers, no central orchestrator | Single SKILL.md + 3 bundled agents |
| **Sub-skill count** | 10 (claude-music-generate, -cover, -repaint, -compose, -export, -analyze, -enhance, -random, -library, -lora) | 0 nested; 5 flat peers (acestep, acestep-songwriting, acestep-lyrics-transcription, acestep-simplemv, acestep-thumbnail, acestep-docs) | 19+ sub-skills | 21+ sub-skills | 52 skills | 0 sub-skills |
| **Orchestrator line count** | 177 | 291 | ~300 (sample seo-audit: 137; actual `skills/seo/SKILL.md` not measured separately) | ~286 (sample blog-analyze) | N/A (no orchestrator) | ~150 (skill-creator body) |
| **Script execution model** | Direct Python API via `uv run` + `sys.path.insert` | REST API client: bash + curl + jq against `http://127.0.0.1:8001` | Python scripts via venv | Python scripts + Node scripts | Python + MCP server at `servers/bitwize-music-server/` | Python scripts (9) |
| **Has `.claude-plugin/plugin.json`** | ❌ MISSING | ❌ (distributed with ACE-Step install) | ✅ `.claude-plugin/plugin.json` + `marketplace.json` | ✅ Same | ✅ Same | N/A (not plugin-packaged) |
| **Has LICENSE file** | ❌ MISSING (README says MIT) | N/A (part of ACE-Step repo — Apache 2.0 inherited) | ✅ LICENSE | ✅ LICENSE | ✅ LICENSE | ✅ LICENSE.txt per-skill |
| **Has `tests/` directory** | ❌ MISSING | ❌ | ❌ | ✅ 3 test files | ✅ **63 test files** (by far the most thorough) | ❌ (has `eval-viewer/` + `assets/eval_review.html` — eval-driven) |
| **Has CI (.github/workflows/)** | ❌ MISSING | ❌ | ✅ `ci.yml` | ✅ `ci.yml` | ✅ 5 workflows (auto-release, model-updater, pr-target-check, test, version-sync) | ❌ |
| **Has `agents/` subagents** | ❌ MISSING | ❌ | ✅ seo-backlinks, seo-cluster, seo-content, seo-dataforseo, seo-drift (5+) | ✅ blog-researcher, blog-reviewer, blog-seo, blog-writer (4+) | ✅ Per-skill subagents (`skills/*/agents/`) | ✅ analyzer, comparator, grader |
| **Has references/ directory** | ✅ 7 files | ❌ (only api-reference.md at SKILL level) | ✅ Per sub-skill (e.g. `skills/seo-sxo/references/`) | ✅ Per sub-skill | ✅ | ✅ `references/schemas.md` |
| **Reference file attribution** | ❌ 0/7 cite sources | N/A | ✅ (partial) | ✅ (partial) | ✅ | ✅ |
| **MCP server bundled** | ❌ | ❌ | ❌ | ❌ | ✅ `servers/bitwize-music-server/` + `.mcp.json` | ❌ |
| **Has a `rank.py` or quality scoring** | ❌ | ❌ | ❌ | ❌ | ✅ `tests/unit/mastering/` | ✅ (skill-creator has `scripts/run_eval.py` + `aggregate_benchmark.py`) |
| **Error handling style** | JSON error to stdout + exit 1 | Bash colored output + jq parsing | Python exceptions + JSON | Python exceptions + JSON | Python with pytest fixtures | Python with explicit error handling |
| **User-facing polish** | Interactive installer | First-gen GitHub star prompt (`show_star_prompt`) | install.sh + install.ps1 | install.sh + install.ps1 | Makefile + migrations/ | N/A |
| **Plugin keywords** (SEO/discoverability) | N/A (no plugin.json) | N/A | ✅ set | ✅ set | ✅ `["music", "suno", "lyrics", "album", "mastering", "ai-music", "claude-code"]` | N/A |

---

## 2. Script CLI pattern diff

### Our `music_engine.sh` + `music_engine.py`:
- Orchestrator config driven (`config.json` → `ace_step_dir`)
- JSON-in-stderr progress, JSON-out-stdout for Claude parsing
- argparse subcommands (`generate`, `cover`, `repaint`, `extract`, `lego`, `complete`)
- Quality presets (`draft`, `standard`, `high`, `max`)

### ace-step team's `acestep.sh` (44,798 bytes — one big bash file):
- curl + jq against REST API
- Subcommands: `generate`, `random`, `status`, `models`, `health`, `config`
- **Interesting UX patterns worth lifting**:
  - `check_deps()` function enforces curl + jq presence
  - Colored output (RED/GREEN/YELLOW/CYAN) for user-facing status
  - **`show_star_prompt()` on first successful generation** — GitHub star nudge in bash UI (line 40-50). Dual-use: UX + repo discoverability.
  - `json_get()` and `json_get_array()` helper functions wrap jq with error suppression
  - `STAR_MARKER_FILE` pattern to show-once rather than every run
  - UTF-8 lang/LC_ALL forcing for multilingual prompts
  - Output dir derived from skill location: `$(cd "${SCRIPT_DIR}/../../../.." && pwd)/acestep_output` — portable, no absolute-path dependency

### bitwize `claude-ai-music-skills`:
- Per-skill Python + MCP server for heavy ops
- pytest-based test suite with fixtures, unit tests by category (mastering/, state/, sheet_music/, cloud/, mixing/, promotion/, sheet_music/)
- CI runs tests on every PR (auto-release.yml + test.yml)

### claude-seo / claude-blog:
- install.sh + install.ps1 (cross-platform)
- Python venv managed via `pyproject.toml`
- requirements.txt + CHANGELOG.md + CITATION.cff
- PRIVACY.md + CONTRIBUTING.md + CODE_OF_CONDUCT.md + SUPPORT.md

---

## 3. Theme 9 rubric applied to claude-music (40-item scoring)

| # | Rule | Claude-music status | Evidence |
|---|---|---|---|
| 1 | `name` field exists | ✅ PASS | `skills/claude-music/SKILL.md:2` |
| 2 | 1–64 chars | ✅ PASS | `claude-music` = 12 chars |
| 3 | lowercase alphanumeric + hyphens | ✅ PASS | |
| 4 | no leading/trailing/consecutive hyphens | ✅ PASS | |
| 5 | matches parent dir name | ✅ PASS | `skills/claude-music/` |
| 6 | no reserved words | ⚠️ AMBIGUOUS | Uses `claude-` prefix; same pattern as Anthropic's `claude-api` skill — flagged G16 |
| 7 | description non-empty, ≤1024 chars | ✅ PASS | 11 lines, ~550 chars |
| 8 | describes what + when | ✅ PASS | Lines 3-12 of SKILL.md |
| 9 | description in third person | ⚠️ PARTIAL | "AI-powered music production suite..." is 3rd-person; "Use when user says..." breaks into 2nd-person pattern (acceptable in AgriciDaniel's other skills) |
| 10 | combined desc+when_to_use front-loads use case | ✅ PASS | |
| 11 | `disable-model-invocation: true` where applicable | ❌ NOT SET | No skills opt out; this is fine for our use — no destructive actions |
| 12 | `allowed-tools` as space-separated or YAML list | ✅ PASS | YAML list used |
| 13 | `context: fork` + `agent:` for subagent | ❌ NOT USED | Could refactor compose / analyze to fork into Explore subagent |
| 14 | SKILL.md body < 500 lines | ✅ PASS | Orchestrator 177; biggest sub-skill `claude-music-generate` = 114 |
| 15 | L2 body < 5,000 tokens | ✅ PASS | 177 lines × ~60 chars/line ÷ 4 chars/token ≈ 2,655 tokens |
| 16 | L1 metadata ~100 tokens | ⚠️ OVER | 12-line description ≈ 140-160 tokens — 40-60% above ideal. Could trim triggers. |
| 17 | no time-sensitive info / "Old patterns" pattern | ✅ PASS | No dated references |
| 18 | consistent terminology | ⚠️ PARTIAL | Mixes "sub-skill" and "skill"; "/music X" and "`/music X`" formatting |
| 19 | references one level deep | ✅ PASS | `references/*.md` all directly from orchestrator |
| 20 | TOC on reference files >100 lines | ❌ FAIL | `prompt-guide.md` (111), `lora-training.md` (109), `parameters.md` (102) all lack TOC |
| 21 | forward slashes in paths | ✅ PASS | |
| 22 | scripts/, references/ subdirs | ✅ PASS | |
| 23 | descriptive filenames | ✅ PASS | `music_engine.py`, `check_deps.sh`, etc. |
| 24 | scripts handle errors explicitly | ✅ PASS | `music_engine.py` has try/except + JSON error output |
| 25 | no voodoo constants | ⚠️ PARTIAL | Quality preset dicts are clear; some magic numbers in `music_export.sh` (`-14 LUFS`, `-1 dBTP`) are documented in `references/post-processing.md` but not at callsite |
| 26 | script execution intent clear | ✅ PASS | SKILL.md says "run" consistently |
| 27 | gerund-form skill names | ❌ FAIL | Our names: `claude-music-generate` (verb), `-cover` (noun), `-repaint` (verb), `-compose` (verb), `-export` (verb), `-analyze` (verb), `-enhance` (verb), `-random` (adj), `-library` (noun), `-lora` (acronym). Mixed. Best-practice gerund forms would be `generating`, `covering`, `repainting`, etc. |
| 28 | no vague names (helper/utils/tools) | ✅ PASS | |
| 29 | ≥3 evaluations | ❌ FAIL | No tests/ directory |
| 30 | tested with Haiku+Sonnet+Opus | ❌ UNVERIFIED | Not documented |
| 31 | audit bundled scripts | ✅ PASS | Cybersecurity audit completed this session (VULN-001..008 all fixed) |
| 32 | audit external URL fetches | ✅ PASS | No external URL fetches in runtime (research-prompt.md has URLs but they're docs refs, not runtime fetches) |
| 33 | `.claude-plugin/plugin.json` | ❌ FAIL | Not shipped |
| 34 | plugin.json schema compliance | ❌ FAIL | File doesn't exist |
| 35 | marketplace.json | ❌ FAIL | File doesn't exist |
| 36 | SKILL.md as overview + pointers | ✅ PASS | Explicit reference-file table at line 141-149 |
| 37 | avoid presenting multiple options | ⚠️ PARTIAL | `claude-music-enhance` offers both FFmpeg-path and AI-path for denoising — could be tightened |
| 38 | plan-validate-execute for batch ops | ❌ N/A / MISSING | No current batch workflow; relevant for future `rank.py` |
| 39 | MCP tool fully-qualified names | ✅ N/A | No MCP tools currently referenced in SKILL.md |
| 40 | concrete input/output examples | ⚠️ PARTIAL | Some sub-skills have examples; `claude-music-compose` is pure reference |

### Score summary

- ✅ PASS: 22 items
- ⚠️ PARTIAL / AMBIGUOUS: 6 items
- ❌ FAIL: 9 items
- N/A or UNVERIFIED: 3 items

**Pass rate**: 22/37 applicable items = **59.5%** → this is the Theme-9 baseline. Target: >90% after refactor.

---

## 4. Patterns to lift (tagged by source)

| Pattern | Source | Why it matters | Apply to |
|---|---|---|---|
| `.claude-plugin/plugin.json` + `marketplace.json` | claude-seo, claude-blog, bitwize | Dec 2025 open-standard distribution | Repo root |
| Per-plugin `keywords[]` array | bitwize plugin.json | GitHub/marketplace discoverability | plugin.json |
| LICENSE file | All three siblings | Legal hygiene | Repo root |
| `tests/unit/<feature>/` directory organized by sub-skill | bitwize, claude-blog | Catch regressions on cover/repaint param mapping (we had 5 param-mapping bugs in this session alone) | `tests/` |
| `ci.yml` (lint + shellcheck + python -m py_compile + JSON validation) | claude-seo, claude-blog | Prevent merging broken scripts | `.github/workflows/` |
| Per-skill `agents/` with composition/evaluation subagents | claude-seo, claude-blog, anthropic/skill-creator | `claude-music-compose` could fork into an Explore agent for songwriting research; `/music random` could fork into Haiku agent for cheap ideation | `skills/claude-music/agents/` |
| `show_star_prompt` on first successful gen | ace-step-skills | Dual-use: UX + discoverability | `music_engine.sh` or post-run |
| `CITATION.cff` | claude-seo, claude-blog | Academic citability (useful when cited in papers) | Repo root |
| `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SUPPORT.md`, `PRIVACY.md`, `SECURITY.md` | claude-blog | Open-source hygiene | Repo root |
| Per-ref-file TOC for files >100 lines | S3 best-practices rule #20 | Lets Claude preview the ToC via `head -20` without loading the whole file | `prompt-guide.md`, `parameters.md`, `lora-training.md` |
| `install.ps1` (Windows) alongside `install.sh` | claude-seo, claude-blog | ACE-Step supports Windows per its docs; our installer is bash-only | Repo root |
| `pyproject.toml` for Python tooling (ruff, mypy) | claude-seo, claude-blog | Reproducible dev env | Repo root |
| MCP server bundling for heavy ops | bitwize | If we later want a long-running ACE-Step daemon, MCP is the packaging pattern | `servers/` (future) |
| Gerund-form naming (`processing-pdfs`) | Anthropic best-practices S3 #27 | Clarity signal | **Skill names** — renaming is P2; noun+verb mix is explicitly "Acceptable alternative" per S3 |
| `evals/` or `eval/` harness scripts | skill-creator (`scripts/run_eval.py`, `aggregate_benchmark.py`) | Needed for Theme 3 rank.py work | `scripts/rank.py` home |

### Patterns we should NOT lift

| Anti-pattern | Source | Why |
|---|---|---|
| Monolithic 44KB bash script for everything | ace-step-skills `acestep.sh` | Our Python-subcommand architecture is cleaner; their REST-based approach is appropriate for their design but not ours |
| Flat peer skills instead of nested sub-skills | ace-step-skills (acestep-*) | Our orchestrator pattern is what the research plan + claude-seo pattern validate |
| 52 tiny skills with overlapping scope | bitwize | At 10 sub-skills we're in the claude-blog / claude-seo sweet spot; 52 would fragment UX |
| `.first_gen_done` marker at skill root | ace-step-skills | Pollutes user's install; should go in `~/.local/state/claude-music/` instead |
| Magic numbers for ACE-Step params scattered in bash | ace-step-skills | We already centralize in Python `QUALITY_PRESETS` — keep it |
