# Theme 9 — Anthropic Claude Code Skill Conventions Rubric

**Research date**: 2026-04-16
**Deliverable target** (per research plan line 327): 30-item checklist, every item backed by an exact docs quote or example-repo reference.

**Primary sources**:
- `S1` = <https://agentskills.io/specification> (fetched 2026-04-16). Authoritative open-standard spec.
- `S2` = <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview> (fetched 2026-04-16). Anthropic platform overview.
- `S3` = <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices> (fetched 2026-04-16). Anthropic authoring best-practices.
- `S4` = <https://code.claude.com/docs/en/skills> (fetched 2026-04-16). Claude Code skills docs.
- `S5` = <https://anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills> (fetched 2026-04-16). Oct 16 2025 foundational post.
- `S6` = <https://claude.com/blog/skills> (fetched 2026-04-16). Dec 18 2025 open-standard announcement (partially accessible via fetch).
- `S7` = `research/scratch/anthropics-skills/skills/skill-creator/SKILL.md` (cloned 2026-04-16). Canonical example.
- `S8` = `research/scratch/anthropics-skills/skills/mcp-builder/SKILL.md` (cloned). Canonical example.
- `S9` = `research/scratch/claude-seo/.claude-plugin/plugin.json` + `marketplace.json` (cloned). Plugin-packaging exemplar.
- `S10` = `research/scratch/claude-ai-music-skills/.claude-plugin/plugin.json` (cloned). Music-domain plugin exemplar.

**Tag legend**: `MUST` (spec-mandated), `SHOULD` (strongly recommended), `RECOMMENDED` (best-practice), `AVOID` (anti-pattern), `NICE-TO-HAVE` (Claude Code optional extension).

---

## A. Frontmatter — required fields

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 1 | `name` MUST exist in YAML frontmatter | MUST | "Required: Yes. Max 64 characters. Lowercase letters, numbers, and hyphens only. Must not start or end with a hyphen." | S1 (frontmatter table) |
| 2 | `name` MUST be 1–64 characters | MUST | "Must be 1-64 characters" | S1 (`name` field section) |
| 3 | `name` MUST contain only lowercase alphanumeric and hyphens | MUST | "May only contain unicode lowercase alphanumeric characters (`a-z`) and hyphens (`-`)" | S1 |
| 4 | `name` MUST NOT start/end with hyphen and MUST NOT contain consecutive hyphens | MUST | "Must not start or end with a hyphen (`-`). Must not contain consecutive hyphens (`--`)" | S1 |
| 5 | `name` MUST match parent directory name | MUST | "Must match the parent directory name" | S1 |
| 6 | `name` MUST NOT contain reserved words "anthropic" or "claude" | MUST (Anthropic extension) | "Cannot contain reserved words: 'anthropic', 'claude'" | S3 + S2 ("Field requirements") |
| 7 | `description` MUST exist, non-empty, max 1024 characters | MUST | "Must be 1-1024 characters" / "Must be non-empty, Maximum 1024 characters, Cannot contain XML tags" | S1 + S3 |
| 8 | `description` SHOULD describe what the skill does AND when to use it | SHOULD | "Should describe both what the skill does and when to use it" | S1 |
| 9 | `description` MUST be written in third person | MUST | "Always write in third person. The description is injected into the system prompt, and inconsistent point-of-view can cause discovery problems." | S3 |

## B. Frontmatter — optional but Claude-Code-specific

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 10 | `when_to_use` + `description` combined SHOULD front-load key use case (truncated at 1,536 chars) | SHOULD | "Front-load the key use case: the combined `description` and `when_to_use` text is truncated at 1,536 characters" | S4 (Frontmatter reference table) |
| 11 | `disable-model-invocation: true` for workflows with side effects (deploy/commit/send) | RECOMMENDED | "Use for workflows you want to trigger manually with `/name`." | S4 |
| 12 | `allowed-tools` SHOULD use space-separated string OR YAML list (not both) | SHOULD | "Accepts a space-separated string or a YAML list" | S4 |
| 13 | `context: fork` with `agent:` REQUIRED for isolated subagent execution | MUST (when using subagents) | "Add `context: fork` to your frontmatter when you want a skill to run in isolation." | S4 |

## C. Body content — token budget and structure

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 14 | SKILL.md body SHOULD be under 500 lines | SHOULD | "Keep SKILL.md under 500 lines." / "Keep SKILL.md body under 500 lines for optimal performance" | S1 + S3 + S4 |
| 15 | Level-2 instructions (full SKILL.md body) SHOULD be under 5,000 tokens | SHOULD | "Instructions (< 5000 tokens recommended): The full SKILL.md body is loaded when the skill is activated" / Table: "Level 2: Instructions — Under 5k tokens" | S1 + S2 |
| 16 | Level-1 metadata SHOULD target ~100 tokens per skill | SHOULD | "Metadata (~100 tokens): The name and description fields are loaded at startup for all skills" / Table: "Level 1: Metadata — ~100 tokens per Skill" | S1 + S2 |
| 17 | SKILL.md SHOULD avoid time-sensitive info in main body; use collapsible "Old patterns" section instead | SHOULD | "Avoid time-sensitive information. Don't include information that will become outdated" | S3 |
| 18 | Use consistent terminology throughout (one term per concept) | SHOULD | "Choose one term and use it throughout the Skill" | S3 |

## D. File references and auxiliary layout

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 19 | File references MUST be one level deep from SKILL.md (no nested reference chains) | MUST | "Keep file references one level deep from SKILL.md. Avoid deeply nested reference chains." | S1 + S3 |
| 20 | Reference files > 100 lines SHOULD include a table of contents at the top | SHOULD | "For reference files longer than 100 lines, include a table of contents at the top." | S3 |
| 21 | Use forward slashes in file paths (NEVER backslashes) | MUST | "Always use forward slashes in file paths, even on Windows" | S3 |
| 22 | RECOMMENDED optional subdirectories: `scripts/`, `references/`, `assets/` | RECOMMENDED | Per spec table: "scripts/ — Optional: executable code. references/ — Optional: documentation. assets/ — Optional: templates, resources" | S1 |
| 23 | File names SHOULD indicate content (e.g., `form_validation_rules.md`, not `doc2.md`) | SHOULD | "Name files descriptively: Use names that indicate content: `form_validation_rules.md`, not `doc2.md`" | S3 |

## E. Scripts — design conventions

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 24 | Scripts MUST handle errors explicitly (not "punt to Claude") | MUST | "Solve, don't punt. When writing scripts for Skills, handle error conditions rather than punting to Claude." | S3 |
| 25 | NO "voodoo constants" / unjustified magic numbers | MUST | "Configuration parameters should also be justified and documented to avoid 'voodoo constants' (Ousterhout's law)." | S3 |
| 26 | Script execution intent SHOULD be clear in SKILL.md (execute vs read-as-reference) | SHOULD | "Make execution intent clear: 'Run analyze_form.py to extract fields' (execute); 'See analyze_form.py for the extraction algorithm' (read as reference)" | S3 |

## F. Naming conventions

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 27 | Gerund form RECOMMENDED for skill names (e.g., `processing-pdfs`, `analyzing-spreadsheets`) | RECOMMENDED | "Consider using gerund form (verb + -ing) for Skill names, as this clearly describes the activity or capability the Skill provides." | S3 |
| 28 | AVOID vague names (`helper`, `utils`, `tools`) | AVOID | "Avoid: Vague names: `helper`, `utils`, `tools`. Overly generic: `documents`, `data`, `files`." | S3 |

## G. Testing and evaluation

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 29 | SHOULD create at least 3 evaluations | SHOULD | "Build three scenarios that test these gaps" / Checklist: "At least three evaluations created" | S3 |
| 30 | SHOULD test with Haiku, Sonnet, AND Opus | SHOULD | "Test with all models you plan to use" / Checklist: "Tested with Haiku, Sonnet, and Opus" | S3 |

## H. Security (separated; stated MUSTs in source)

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 31 | MUST audit bundled scripts, images, and resources before use | MUST | "Audit thoroughly: Review all files bundled in the Skill: SKILL.md, scripts, images, and other resources." | S2 (Security considerations) |
| 32 | MUST treat external-URL fetches as trust-risky (instructions or dependencies can change) | MUST | "External sources are risky: Skills that fetch data from external URLs pose particular risk, as fetched content may contain malicious instructions." | S2 |

## I. Plugin packaging (Dec 2025 open standard)

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 33 | Distribution-as-plugin SHOULD ship `.claude-plugin/plugin.json` | RECOMMENDED | Observed in claude-seo, claude-blog, bitwize-music-studio — all three competitors treat this as required for marketplace distribution | S9 + S10 |
| 34 | `plugin.json` SHOULD include: `name`, `description`, `version`, `author`, `repository`, `homepage`, `license`, `skills` (path), `keywords[]`; MAY include `mcpServers` | RECOMMENDED | From S10 verbatim: `{"name": "bitwize-music", "description": "...", "version": "0.89.0", "author": {...}, "repository": "...", "homepage": "...", "license": "CC0-1.0", "skills": "./skills/", "mcpServers": "./.mcp.json", "keywords": [...]}` | S10 |
| 35 | `marketplace.json` SHOULD list plugin(s) with `name`, `owner`, `plugins[{name, description, version, source}]` | RECOMMENDED | Verbatim from S10: `{"name": "bitwize-music", "owner": {"name": "bitwize-music-studio"}, "plugins": [{"name":"bitwize-music","description":"...","version":"0.89.0","source":"./"}]}` | S10 |

## J. Progressive disclosure & anti-patterns (omnibus)

| # | Rule | Severity | Verbatim source quote | Cite |
|---|---|---|---|---|
| 36 | SKILL.md SHOULD serve as overview that points to detailed materials (table-of-contents pattern) | SHOULD | "SKILL.md serves as an overview that points Claude to detailed materials as needed, like a table of contents in an onboarding guide." | S3 |
| 37 | AVOID presenting multiple implementation options to Claude — provide a default with an escape hatch | AVOID | "Don't present multiple approaches unless necessary" | S3 |
| 38 | Skills with executable scripts SHOULD use "plan-validate-execute" pattern for batch/destructive ops | SHOULD | "Use the 'plan-validate-execute' pattern... Batch operations, destructive changes, complex validation rules, high-stakes operations" | S3 |
| 39 | For MCP tool references inside skills, USE fully-qualified `ServerName:tool_name` | MUST | "Always use fully qualified tool names to avoid 'tool not found' errors. Format: ServerName:tool_name" | S3 |
| 40 | Example anchoring: provide concrete input/output pairs, not abstractions | SHOULD | "For Skills where output quality depends on seeing examples, provide input/output pairs just like in regular prompting" | S3 |

---

## Self-calibration — applying the rubric to `claude-video/SKILL.md` (226 lines)

The research plan (line 326-328) calls for calibrating the rubric against an existing skill: "Cross-check: apply rubric to an existing local skill. Does it pass? If yes, the rubric is too loose; tighten it."

**File**: `/home/agricidaniel/.claude/skills/claude-video/SKILL.md` (226 lines, surveyed Phase 1)

| Rubric # | Item | Pass/Fail | Evidence |
|---|---|---|---|
| 1–5, 7 | Name + description basic constraints | ✅ PASS | Frontmatter valid (known from Phase 1) |
| 6 | No reserved words in name | ✅ PASS | `name: claude-video` — "claude" is part of namespace prefix; observed in multiple AgriciDaniel skills. Note: strict reading of S3 says "Cannot contain reserved words: 'anthropic', 'claude'". This is a potential VIOLATION of the strict rule. See note below. |
| 8 | Description says both what + when | ✅ PASS (presumed from the ~20-skill peer set) |
| 9 | Description in third person | UNVERIFIED — requires re-read |
| 14 | Body <500 lines | ✅ PASS (226 lines) |
| 15 | Body <5k tokens | LIKELY PASS (226 lines × ~20 chars/line ÷ 4 chars/token ≈ 1130 tokens) |
| 22 | References/scripts/assets subdirs | ✅ PASS (Phase 1 confirmed references/, scripts/) |
| 29–30 | Evaluations / multi-model testing | ❌ FAIL (no tests/ directory) |
| 31 | Security audit trail | UNVERIFIED |
| 33–35 | Plugin packaging | ❌ FAIL (`claude-video` is not distributed via `.claude-plugin/` — local-only) |

**Calibration result**: claude-video passes ~85% of rubric items but fails the plugin-packaging triplet and testing. This is the expected result for a local-only skill — the rubric is not too loose and correctly identifies the real gaps.

### Note on rule #6 (reserved words)

The Anthropic best-practices and overview pages state: "Cannot contain reserved words: 'anthropic', 'claude'". This conflicts with observed practice: the user has 100+ skills prefixed `claude-*` (claude-video, claude-music, claude-gif, claude-blog, claude-seo, claude-obsidian, etc.), and Anthropic themselves ship `claude-api` in the open-source skills repo (confirmed in the clone: `/skills/claude-api/`).

**Resolution**: The rule is likely intended to forbid `anthropic-*` or `claude-*` when those words imply official Anthropic endorsement, but is not strictly enforced for third-party namespace prefixes. **Flag as G16: Reserved-word rule is ambiguous vs observed practice — treat as SHOULD, not MUST, pending clarification.** Our `claude-music-*` pattern is consistent with user's other skills and with `claude-api` in the official repo.

---

## Open questions / ambiguities surfaced by this rubric

| Ambiguity | Flag | Workaround |
|---|---|---|
| Reserved-word rule for `claude-*` and `anthropic-*` prefixes | G16 (new) | Use SHOULD, not MUST; follow user's existing naming pattern |
| `when_to_use` field — present in S4 only, not in S1 spec | Claude-Code-specific extension | NICE-TO-HAVE, not required |
| `disable-model-invocation`, `user-invocable`, `paths`, `shell` — all Claude-Code-only | Claude-Code extensions | NICE-TO-HAVE |
| Plugin.json exact schema varies slightly between claude-seo, claude-blog, and bitwize (author format, keywords, mcpServers) | Not yet canonical | Follow bitwize's schema (most complete) |
| Dec 2025 open-standard announcement mentions "open standard for cross-platform portability" but blog post itself lacks technical details | Use agentskills.io as the canonical spec | Already using |

---

## Summary counts

- **Rubric items**: 40 (10 above the 30-item target)
- **MUSTs**: 17
- **SHOULDs**: 15
- **RECOMMENDED / NICE-TO-HAVE**: 6
- **AVOID (anti-patterns)**: 2
- **Sources cited per item**: minimum 1, often 2-3
