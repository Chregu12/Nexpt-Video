# Theme 10 — claude-music Refactor Plan

**Research date**: 2026-04-16
**Baseline**: Theme 9 rubric pass rate = 22/37 = **59.5%**
**Target**: ≥90% pass rate + model-ceiling song quality per user's 100/100 goal
**Deliverable** (per research plan line 364): ≥15 specific changes, each tagged with source pattern, priority, and estimated implementation cost.

**Priority key**:
- **P0**: Blocks any Theme 1–8 progress OR ships incorrect/legally-risky code. Must land before any other refactor.
- **P1**: Blocks a specific Theme. Lands during or immediately before that Theme's session.
- **P2**: Quality-of-life / discoverability / polish. Lands whenever.

**Source key**: tags identify which doc or competitor taught the change, per research plan ground rules ("Every change tagged by the research theme and source that justifies it").

---

## P0 — Must land before any other theme

### R1. Add LICENSE file

- **Change**: Add `LICENSE` at repo root with MIT content matching README's stated license.
- **Why**: README claims MIT but repo has no LICENSE file; this makes MIT claim unenforceable and blocks clean distribution.
- **Source**: All three siblings (claude-seo, claude-blog, bitwize) ship LICENSE; Theme-9 rubric item #31 (security/audit hygiene).
- **Cost**: 5 min (boilerplate MIT + SPDX header).
- **File**: `LICENSE`

### R2. Attribute the 7 reference docs

- **Change**: Add a `## Sources` section at the bottom of each reference file citing the Musician's Guide, Tutorial.md, paper, or research-report section that justified each claim. For claims not yet sourced, flag as TODO for Theme 1.
- **Why**: Phase-1 audit found 0/7 references cite sources; this makes them un-reviewable and untrustworthy for a quality-focused skill.
- **Source**: Research plan Theme 1 line 45 — "each recipe [...] 3+ documented sources"; Theme-9 rubric item #17 (time-sensitivity); research plan ground rule "flag every gap".
- **Cost**: 1 h (find one source per reference-doc section, add footnote).
- **Files**: `skills/claude-music/references/*.md` (all 7)

### R3. Remove `research-prompt.md` and `ace-step-research-report.md` from git-tracked repo root

- **Change**: Move to `research/drafts/` (gitignored) OR publish explicitly under `research/published/` with date + version suffix.
- **Why**: Research artifacts as top-level files confuse users browsing the repo and inflate the clone size (41KB + 19KB of text noise).
- **Source**: claude-seo / claude-blog ship a clean root with only operational files; observed pattern.
- **Cost**: 10 min.
- **Files**: move 2 files, update `.gitignore`.

### R4. Decide and document: Python API vs REST API

- **Change**: Add an `ARCHITECTURE.md` in the repo root justifying the Python-API-direct choice, with explicit pros/cons vs the ace-step team's REST-API approach. Add one-sentence justification in README.
- **Why**: Research plan line 360 says to "lift the local-REST-API pattern" from ace-step-skills. We intentionally chose Python API. This decision must be documented so future maintainers don't silently flip it.
- **Source**: Research plan Theme 10 line 360 (patterns to lift) + ace-step-skills `acestep.sh` (observed alternative).
- **Decision to document**: We chose Python API because (a) no REST server process to manage at install time; (b) full `GenerationParams` field access (REST completion-mode hides `inference_steps`, `shift`, `infer_method`); (c) the 15-30s cold-start cost is amortized within a single `/music generate` call and is acceptable for the iteration-driven "human-centered generation" philosophy from Tutorial.md.
- **Cost**: 30 min to write.
- **File**: `ARCHITECTURE.md`

### R5. Remove tracked `.claude/` directory fragments

- **Change**: Verify `.claude/settings.json` is fully out of git history (it was deleted, confirm in git log); keep `.claude/` in `.gitignore`. No-op if already clean.
- **Why**: Previous session's security audit VULN-005; re-verify before going further.
- **Source**: `claude-cybersecurity` skill audit from prior session (VULN-005).
- **Cost**: 5 min (verify).
- **File**: `.gitignore` + git audit.

---

## P1 — Blocks specific research themes

### R6. Add `.claude-plugin/plugin.json` and `marketplace.json`

- **Change**: Create `.claude-plugin/plugin.json` with schema matching bitwize's (name, description, version, author, repository, homepage, license, skills path, keywords). Create `marketplace.json` with single-plugin entry.
- **Schema (lift from bitwize S10)**:
```json
{
  "name": "claude-music",
  "description": "AI-powered music production suite using ACE-Step 1.5 via direct Python API. Song generation, cover, repaint, compose, analyze, export, enhance, lora.",
  "version": "0.1.0",
  "author": {"name": "AgriciDaniel"},
  "repository": "https://github.com/AgriciDaniel/claude-music",
  "homepage": "https://github.com/AgriciDaniel/claude-music#readme",
  "license": "MIT",
  "skills": "./skills/",
  "keywords": ["music", "ace-step", "music-generation", "ai-music", "text-to-music", "cover", "repaint", "lora", "claude-code"]
}
```
- **Why**: Dec 18 2025 announcement established Agent Skills as open standard; all 3 sibling skills ship plugin metadata; required for Marketplace distribution.
- **Source**: Theme-9 rubric items #33-35; claude-seo, claude-blog, bitwize all ship this.
- **Cost**: 20 min.
- **Files**: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`.
- **Blocks**: Theme 10 deliverable ("PR-ready refactor") and Theme 11 gap G15.

### R7. Add `tests/` directory with skill-contract tests

- **Change**: Create `tests/test_music_engine.py` covering:
  (a) JSON output contract (`--help` returns nonzero but all subcommands return valid JSON to stdout);
  (b) config.json path resolution (CHANGE_ME placeholder is rejected);
  (c) Cover-mode `src_audio` + `cover_noise_strength` mapping (regression guard against the bug we fixed last session where the code had `reference_audio` + `audio_cover_strength`);
  (d) Quality preset resolution (draft/standard/high/max map to expected models).
- **Why**: Session-2 bug fixes (VULN-001..008 and the `src_audio` mapping discovery) prove untested code regresses silently. Every Theme-2+ compute investment is at risk without contract tests.
- **Source**: bitwize has 63 test files; claude-blog has 3; skill-creator has an eval harness. Theme-9 rubric #29 ("at least three evaluations").
- **Cost**: 2 h (4 tests × 30 min each with fixtures).
- **Files**: `tests/test_music_engine.py`, `tests/conftest.py`.
- **Blocks**: all subsequent themes (need regression guard before changing params).

### R8. Add `.github/workflows/ci.yml`

- **Change**: Single workflow running: shellcheck on `scripts/*.sh`, `python -m py_compile` on `scripts/*.py`, `python -m json.tool` on `config.json` and `.claude-plugin/*.json`, `pytest tests/`.
- **Why**: Dec 18 2025 open-standard stance + distribution via marketplace requires confidence that PRs don't break the skill.
- **Source**: claude-seo ci.yml, claude-blog ci.yml, bitwize 5-workflow setup.
- **Cost**: 30 min (copy from claude-blog, adapt paths).
- **File**: `.github/workflows/ci.yml`.
- **Blocks**: R6 distribution path.

### R9. Create `scripts/rank.py` skeleton + `references/ranking-method.md` stub

- **Change**: Stub out `rank.py` with argparse skeleton expecting `--input-dir` (directory of generated flac files) and `--caption` (the original caption to score against). Stub implementation returns a JSON report with placeholder scores. Document the plan in `references/ranking-method.md`: CLAP caption-cosine, SongEval dims, DNSMOS, LLM-judge weighting per Theme 3.
- **Why**: Research plan Theme 3 requires an output `rank.py` design document; creating the stub now establishes the CLI contract so Theme 2 benchmark runs can emit files that Theme 3 will consume.
- **Source**: Research plan Theme 3 line 113 ("Output = a concrete `rank.py` design document"); skill-creator `scripts/run_eval.py` as pattern.
- **Cost**: 1 h (skeleton + reference md).
- **Files**: `skills/claude-music/scripts/rank.py`, `skills/claude-music/references/ranking-method.md`.
- **Blocks**: Theme 3 end-to-end.

### R10. Add TOC headers to reference files > 100 lines

- **Change**: Add `## Contents` section at top of `prompt-guide.md` (111 lines), `lora-training.md` (109 lines), `parameters.md` (102 lines).
- **Why**: Claude may partially read files via `head -N`. TOC at top lets it see full scope even on partial load.
- **Source**: Theme-9 rubric item #20, verbatim from best-practices: "For reference files longer than 100 lines, include a table of contents at the top."
- **Cost**: 15 min.
- **Files**: 3 reference files.

### R11. Trim orchestrator description to ~100-token budget

- **Change**: Current orchestrator description is 12 lines (~140-160 tokens). Collapse to ~4 lines (~90 tokens) while keeping trigger-phrase coverage. Move verbose trigger list to `when_to_use:` field (separate field per S4), which shares the 1,536-char combined budget.
- **Why**: Theme-9 rubric #16 targets ~100 tokens per L1 metadata; every skill in a multi-skill repo competes for this budget.
- **Source**: S2 overview table ("Level 1: Metadata — ~100 tokens per Skill"); S4 `when_to_use` field.
- **Cost**: 15 min.
- **Files**: `skills/claude-music/SKILL.md` frontmatter + all 10 sub-skill SKILL.md frontmatters.

### R12. Add `install.ps1` (PowerShell installer)

- **Change**: Port `install.sh` to PowerShell for Windows users. ACE-Step supports Windows; our installer should too.
- **Why**: bitwize skill supports Windows via Makefile + migrations; claude-seo + claude-blog ship install.ps1 alongside install.sh. Without Windows support we exclude a substantial user slice.
- **Source**: claude-seo, claude-blog observed pattern.
- **Cost**: 1 h (port ~170 lines with Windows-appropriate path handling and uv installation).
- **File**: `install.ps1`.

### R13. Add `pyproject.toml` at repo root

- **Change**: Minimal `pyproject.toml` declaring: project name, version, Python version, dev dependencies (`pytest`, `ruff`, `mypy`). Declares the repo as a Python project for tooling integration.
- **Why**: Enables `pytest tests/` (R7), `ruff check` in CI (R8), and `uv sync --dev` for contributor onboarding.
- **Source**: claude-seo, claude-blog both ship pyproject.toml.
- **Cost**: 15 min.
- **File**: `pyproject.toml`.

---

## P2 — Quality-of-life and discoverability

### R14. First-run GitHub star nudge in `music_engine.sh`

- **Change**: Port ace-step's `show_star_prompt()` and `STAR_MARKER_FILE` pattern to `music_engine.sh`. Shows once after first successful generation; marker file in `~/.local/state/claude-music/.first_gen_done` (NOT in skill directory like ace-step does — that's the one anti-pattern from ace-step to avoid per Theme-10 diff).
- **Why**: Dual-purpose UX + repo discoverability. Low cost, high value.
- **Source**: ace-step-skills `acestep.sh:40-50`.
- **Cost**: 20 min.
- **File**: `skills/claude-music/scripts/music_engine.sh`.

### R15. Add `agents/` subagent for `claude-music-compose`

- **Change**: Create `skills/claude-music/agents/music-composer.md` — a subagent that, when invoked via `context: fork` in `claude-music-compose`, runs as an Explore agent to research genre-specific song structures and return structured caption+lyrics+params JSON. This is the first step toward the multi-model routing pattern (R17).
- **Why**: Composition is the highest-reasoning part of the workflow; running it in a forked context saves the main session's tokens. Research plan Theme 10 line 361 calls out "subagent-per-major-task" as a pattern from claude-seo.
- **Source**: claude-seo `agents/seo-content.md` pattern; anthropic/skill-creator `agents/analyzer.md|comparator.md|grader.md` triad.
- **Cost**: 2 h (write agent + wire into compose sub-skill frontmatter with `context: fork, agent: music-composer`).
- **Files**: `skills/claude-music/agents/music-composer.md`, update `skills/claude-music-compose/SKILL.md`.

### R16. Community-health files: CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, CITATION.cff

- **Change**: Ship minimal versions of each. CONTRIBUTING: how to add a genre recipe, how to run tests, the PR checklist. SECURITY: audit pattern + vuln-reporting email. CITATION.cff: machine-readable citation.
- **Why**: Standard OSS hygiene; claude-seo and claude-blog both ship these.
- **Source**: claude-blog file tree observed; GitHub recommended community standards.
- **Cost**: 1 h.
- **Files**: 4 new files at repo root.

### R17. Multi-model routing via `model:` frontmatter field

- **Change**: Set `model: haiku` on `claude-music-random` (cheap ideation); `model: opus` on `claude-music-compose` (complex songwriting reasoning); leave orchestrator + others to session default (Sonnet).
- **Why**: Bitwize cites "multi-model routing Opus/Sonnet/Haiku" as one of its distinguishing patterns; research plan Theme 10 line 361 calls this out as a pattern to lift. Using Haiku for `/music random` saves tokens on 4-variant batches.
- **Source**: bitwize plugin routing pattern; Theme-9 rubric #12 (`model` frontmatter field from S4).
- **Cost**: 10 min (just frontmatter edits).
- **Files**: 2 sub-skill SKILL.md files.

### R18. Add `compatibility:` frontmatter to orchestrator

- **Change**: Add `compatibility: "Requires ACE-Step 1.5 install + NVIDIA GPU ≥4GB VRAM (12GB+ recommended). See config.json for ace_step_dir."` to orchestrator frontmatter.
- **Why**: Theme-9 rubric #9 optional field makes hard requirements visible at L1 metadata level.
- **Source**: S1 spec `compatibility` field.
- **Cost**: 5 min.
- **File**: `skills/claude-music/SKILL.md`.

### R19. Consider renaming sub-skills to gerund form

- **Change**: Optional. `claude-music-generating`, `-covering`, `-repainting`, `-composing`, `-exporting`, `-analyzing`, `-enhancing`, `-randomizing`, `-library-managing`, `-lora-training`.
- **Why**: Theme-9 rubric #27 recommends gerund form. S3 explicitly lists "noun phrases" and "action-oriented" as acceptable alternatives, so this is NOT a compliance fix — it's a style consistency fix if and only if we want to match the Anthropic-recommended pattern.
- **Recommendation**: **SKIP for now.** Renaming breaks existing installations and is explicitly called "Acceptable alternative" by S3. Flag for v2.0 if we do a major version bump.
- **Source**: S3 naming conventions section.
- **Cost**: 2 h (rename + update all cross-references + update install.sh symlinks).
- **File**: N/A — deferred.

### R20. Consolidate scripts to `references/` awareness

- **Change**: Add a `## Scripts` section at the bottom of each reference file that uses a script (e.g., `post-processing.md` should reference `music_export.sh` and list each platform preset). Reduces drift between docs and code.
- **Why**: Theme-9 rubric #26 (script execution intent clear).
- **Source**: S3.
- **Cost**: 30 min.
- **Files**: 2-3 reference files.

---

## Summary — Refactor plan totals

- **P0**: 5 items, ~2.2 hours total, must land before other themes begin.
- **P1**: 8 items, ~5.5 hours total, lands during or before Theme 3.
- **P2**: 7 items, ~4.5 hours total, lands anytime.
- **Grand total**: 20 refactor items (exceeds the ≥15 research-plan target by 5), ~12 hours of implementation work.

### Theme-9 rubric re-check after refactor

If all P0+P1 items land: baseline 22/37 → projected **32/37 = 86.5%**.
If all 20 items land: projected **35/37 = 94.6%**. Items #6 (reserved words ambiguity) and #19 (gerund-form rename, deferred) remain the only non-passes.

### What this refactor does NOT do

- It does NOT ship any song-quality improvements. Those come from Themes 1 (prompts), 2 (params), 3 (rank), 4 (editing), 6 (post-processing). The refactor lands the infrastructure those themes need.
- It does NOT change the Python-API vs REST-API architecture decision. R4 only documents it.
- It does NOT install audio-analysis tooling (librosa/CLAP/SongEval). That's a Theme-3 prerequisite (gap G12), deferred to Session 3.

### Tag legend — each item traceable to:

| Tag | Meaning |
|---|---|
| (Theme 9 #N) | Corresponds to rubric item N in `theme-9-anthropic-rubric.md` |
| (S1–S10) | Source citation per Theme 9 rubric sources |
| (bitwize / ace-step / claude-seo / claude-blog / skill-creator) | Pattern lifted from that skill |
| (research plan line N) | Research plan verbatim directive |

All 20 items traceable. Each ships with a PR-ready unit of scope.
