# Contributing to medit

Issues and pull requests are welcome — bug reports, new sounds, new effects, UI fixes, docs.

- Read [AGENTS.md](AGENTS.md) first: it is the contract for humans and coding agents alike
  (code map, the rules that keep the engine consistent, how to verify).
- Code and comments are **in Italian** (project convention); everything a user reads (UI text,
  error messages, tool and effect descriptions) is **in English**. If you change `README.md`,
  align `README.it.md` too.
- **Every edit to the song goes through `Store`.** Never write the document from `api.py`,
  `mcp_server.py` or `cli.py`.
- Every new behaviour comes with a test. A tone effect needs a *direction* test in
  `tests/test_render.py` (does the EQ actually cut where it says?), not only that it renders.
- New effect → `effects.REGISTRY`. New sound → `presets.SOUNDS`, then recalibrate levels with
  `scripts/calibra_suoni.py`. New MCP tool → a method in `store.py`, a wrapper in `mcp_server.py`
  (its docstring becomes the tool description), a test.
- UI change → `cd frontend && npm run build`, otherwise the server serves the old `dist`.
- Before claiming it works: `pytest`, plus `cd frontend && npm test` if you touched the UI.
- No new dependencies without a reason: the core stands on numpy, scipy, soundfile, mido,
  Pillow, FastAPI and mcp.

## Setup

```bash
git clone https://github.com/metiutek/editormusic-ai
cd editormusic-ai
python scripts/setup.py        # dependencies, UI build, tests (--venv for a virtualenv)
medit doctor
```
