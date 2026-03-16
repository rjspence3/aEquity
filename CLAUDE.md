# aEquity — Claude Code Project Context

## Stack

- **Python 3.11+** — use 3.11-compatible syntax only
- **Dependencies** managed in `pyproject.toml` — do not create `requirements.txt`
- **Pydantic v2** for schemas, **pydantic-settings** for config

## Key Commands

```bash
ruff check .                          # lint
mypy --ignore-missing-imports .       # type check
pytest tests/ -v                      # run all tests
pytest tests/ --cov=. --cov-report=term-missing  # with coverage
python main.py AAPL                   # single-stock CLI
streamlit run app.py                  # dashboard
python batch.py --limit 20            # batch analysis
```

## Architecture Notes

- `pipeline.py::analyze_ticker()` is the core entry point — ~270 lines, linear, intentionally not split
- `scoring_config.py` is the single source of truth for all tunable constants
- `tools/calculator_tools.py` accept `yf.Ticker` objects (not ticker strings) to avoid redundant HTTP fetches
- `tools/sec_tools.py::fetch_10k_sections()` requires `SEC_USER_AGENT_EMAIL` in settings

## Conventions

- **Normalization functions** (e.g. `normalize_roic`) return `int` in range 0–100
- **Raw calculation functions** (e.g. `calculate_roic`) return `float | None`
- Missing data degrades scores gracefully via weighted averaging — never silently shifts toward 50
- Pillar weights are in `scoring_config.py::ENGINE_WEIGHTS`, `FORTRESS_WEIGHTS`, `ALIGNMENT_WEIGHTS`
- Verdict boundaries: 80 = Strong Buy, 65 = Buy, 45 = Hold, 30 = Avoid, <30 = Strong Avoid

## Environment Variables

See `.env.example`. Required: `ANTHROPIC_API_KEY`, `SEC_USER_AGENT_EMAIL`.
