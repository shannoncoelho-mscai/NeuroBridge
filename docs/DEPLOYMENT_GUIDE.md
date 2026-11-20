# Deployment guide

**Status: prototype, not production-ready.** Before any real deployment:

* add authentication and authorisation: `caregiver_user_id` is currently trusted from the client;
* persist agent runs and approvals (they are in memory now);
* restrict CORS, put the app behind HTTPS, add rate limiting and audit logging;
* replace keyword safety detection with a reviewed classifier, plus human escalation paths;
* run the live evaluation (`scripts/live_eval.py`) and the model evaluation protocol;
* merge with the platform backend in `neurobridge-platform-phase1.zip`, which already
  has a Dockerfile and docker-compose. This repository has no container build of its own.

Single-host demo: `uvicorn agent.api.app:app --host 0.0.0.0 --port 8000` with the
environment variables from ENVIRONMENT_SETUP.md.
