# Installation

* App (CPU is fine): `pip install -r requirements.txt`, then
  `uvicorn agent.api.app:app --port 8000`, then open `/ui`.
* Training (GPU): `pip install -r neurobridge_llm/requirements-train.txt` (pinned to versions
  that worked on Colab T4/CUDA 13), or use `neurobridge_llm/NeuroBridge_LLM_Pipeline.ipynb`.
* Tests: `python -m pytest -q tests/`.

See README.md for Colab steps and ENVIRONMENT_SETUP.md for configuration.
