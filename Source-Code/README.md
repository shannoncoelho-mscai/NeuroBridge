# Source code

The source code is kept in the repository's top-level folders:

| Folder | Contents |
|---|---|
| [`../agent/`](../agent/) | Research agent: planner, executor, tools, research and verification, safety layer, LLM gateway (Groq, Gemini, local Qwen), memory, skills, MCP server, API |
| [`../nbapp/`](../nbapp/) | Web application: accounts and roles, consent, daily-support and caregiver pages, Community Connect, appointments, assistant, user interface (`static/`) |
| [`../neurobridge_llm/`](../neurobridge_llm/) | Dataset pipeline, QLoRA SFT, ORPO, evaluation, human evaluation, Colab training notebook |
| [`../scripts/`](../scripts/) | Key check, demo data, live evaluation |
| [`../tests/`](../tests/) | Automated tests (`python -m pytest -q tests/`) |
| [`../backups/`](../backups/) | Untouched reconstruction of the original notebook code |

Run: `pip install -r requirements.txt` then `uvicorn agent.api.app:app --port 8000` and open `http://localhost:8000/app`.
