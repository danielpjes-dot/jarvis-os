# Changelog

## 2.1.0 — 2026-07-05

### Added
- **systemd migration**: 17 user units + `systemd/install.sh` (`--start`/`--uninstall`), umbrella `jarvis.target`, auto-start at WSL boot via linger, shutdown memory snapshot via stop-ordering trick
- **Self-healing plan runner**: crash auto-recovery (orphaned in-flight tasks re-queued at daemon start), dep-timeout re-queue (3×) instead of cascade failure, retry backoff, `JARVIS_DEP_TIMEOUT`/`JARVIS_PLAN_WORKERS` env tuning
- **Failure diagnosis loop**: exhausted retries trigger an LLM diagnosis (CAUSE/FIX, `JARVIS_DIAG_MODEL`), appended to `<vault>/.jarvis/plan_failures.md`, plus one diagnosis-guided retry with the fix injected into the coder prompt
- **Plan rerun**: `POST /rerun/{plan_id}` + `plan` skill `rerun` action — clones a plan under a versioned ID (`PLAN-X-001` → `-2` → `-3`)
- **Claude API mode**: `scripts/claude_proxy.py` emulates Ollama (`/api/chat`, `/api/generate`, `/api/tags`, `/api/embeddings`) and llama.cpp (`/v1/chat/completions`) over the Anthropic API; tool-call format translation both ways; optional Voyage AI embeddings; `jarvis-claude-proxy` unit (Conflicts=jarvis-ollama)
- **Backend fallback chain**: llama.cpp down → automatic Ollama fallback in react_server (both call sites) and memory_router (`JARVIS_ROUTER_FALLBACK_MODEL`)
- **Ollama minimum-model guard**: gemma 4b-class models are never sent to Ollama — bumped to `JARVIS_OLLAMA_MIN_MODEL` (default qwen3:14b)
- **Multi-message Telegram**: `---next---` marker in any reply auto-splits into separate messages at the gateway; over-limit messages chunk at line boundaries instead of silent truncation
- **chatterbox_skill**: full loader interface (TOOLS/TOOL_MAP/KEYWORDS/SKILL_META)
- `scripts/jarvis_boot_init.py`: one-shot boot init extracted from jarvis.sh inline Python

### Fixed
- **Duplicate telegram_watcher** (permanent Telegram HTTP 409): jarvis.sh and loop.sh both started it — loop.sh now owns it (jarvis.sh path), `jarvis-telegram.service` owns it under systemd
- **coding prompt bomb**: directory reads no longer rglob 16k+ site-package files — skip-dirs + 20 file / 120KB caps
- **coding backend routing**: no model hint now defaults to the qwen3-coder backend instead of the placeholder-only generic backend
- **memory skill**: `memory_search` no longer requires the nonexistent mempalace module — falls back to direct Obsidian vault text search; `SKILL_NAME` collision with memory_core resolved (renamed to `mempalace`)
- **shell skill collisions**: shell.py renamed to `shell_diagnostics`, its `read_file` tool renamed to `read_source_file` (shell_skill.py owns `shell`/`read_file`)
- **react_server**: duplicate `request_llama_cpp_chat` definition silently overrode the payload-translating version (renamed raw variant)
- **memory_router**: llama.cpp downtime no longer masked as "I didn't catch that" — escalates to reason with the real error logged; `CHAT_CONFIDENCE_MIN` 0.9 → 0.75 (env-tunable); Pass-2 fetch-plan LLM call off by default (`JARVIS_FETCH_PLAN_LLM=1` to re-enable)
- **plan_runner skill loading**: project root on sys.path and modules registered in sys.modules before exec (fixes `email.py` and dataclass-based skills)
- **news skill**: one Telegram message per headline; env fallback to `JARVIS_TELEGRAM_BOT_TOKEN`/`JARVIS_TELEGRAM_ALLOWED_CHAT_IDS` (previous names didn't exist — push was silently dead)
- **loader.py**: accepts both `{"enabled": ...}` and legacy `{"skills": ...}` in config/skills.json

### Notes
- WSL2 shuts its VM down when the last `wsl.exe` client exits — run a keep-alive (`wsl.exe -e sleep infinity`, e.g. from the Windows Startup folder) or Jarvis only lives while a terminal is open
- Ollama's installer registers a system-level `ollama.service`; don't enable the `jarvis-ollama` user unit alongside it

## 2.0.0

Baseline: modular skills, plan system, memory router, Stark HUD, UE 5.8 MCP, Telegram gateway, n8n integration.
