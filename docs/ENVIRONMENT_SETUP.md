# Environment setup

Never commit keys. Use environment variables locally and Colab Secrets in Colab. No
endpoint returns key values.

| Variable | Purpose | Default |
|---|---|---|
| `GROQ_API_KEY`, `GEMINI_API_KEY` | hosted LLM providers | unset |
| `TAVILY_API_KEY` | web search + page extraction | unset (DDGS fallback if `ddgs` installed) |
| `NEUROBRIDGE_DEFAULT_PROVIDER` | active provider | `groq` |
| `NEUROBRIDGE_GROQ_MODEL` / `NEUROBRIDGE_GEMINI_MODEL` | model ids | `openai/gpt-oss-120b` (fallback `gpt-oss-20b`) / `gemini-3.8-flash` (fallbacks listed in AI_MODEL_GUIDE) |
| `NEUROBRIDGE_SEARCH_COUNTRY` | Tavily country boost | `india` (empty = no boost) |
| `NEUROBRIDGE_LOCAL_MODEL` | local HF base model | unset |
| `NEUROBRIDGE_SFT_ADAPTER` (alias `NEUROBRIDGE_ADAPTER_PATH`) | SFT LoRA adapter → provider `nb_sft` | unset |
| `NEUROBRIDGE_ORPO_ADAPTER` | SFT+ORPO LoRA adapter → provider `nb_sft_orpo` | unset |
| `NEUROBRIDGE_LOCAL_REPETITION_PENALTY` | local-model generation | `1.1` |
| `NEUROBRIDGE_SEED_DEMO_EVENTS` | add labelled demo events at startup | unset |
| `NEUROBRIDGE_LOCAL_4BIT` | 4-bit loading on GPU | `1` |
| `NEUROBRIDGE_ENV` | `production` or `development` | `production` |
| `NEUROBRIDGE_LLM=mock` | dev mock provider (development only) | unset |
| `NEUROBRIDGE_ADMIN_TOKEN` | provider verification / slot admin | unset (admin endpoints disabled) |
| `NEUROBRIDGE_BOOKING_DB` | booking SQLite path | `data/neurobridge_bookings.sqlite3` |
| `NEUROBRIDGE_CORS_ORIGINS` | comma-separated allowed origins | `*` |
| `NEUROBRIDGE_AUTO_INIT` | build providers on startup | `1` |

Installation steps are in README.md ("Run locally" / "Run in Google Colab").
