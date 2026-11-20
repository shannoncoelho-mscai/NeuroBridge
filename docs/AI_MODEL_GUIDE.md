# AI model guide

## Providers

NeuroBridge talks to models through `agent/llm/gateway.py` (provider registry +
fallback). Providers are configured only through environment variables (`agent/bootstrap.py`):

| Provider | Enable with | Notes |
|---|---|---|
| Groq | `GROQ_API_KEY` | default model `openai/gpt-oss-120b` |
| Gemini | `GEMINI_API_KEY` | default `gemini-3.8-flash`; on 404 (not enabled for the key) or 503 (busy) tries `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-2.5-flash`. Thinking set to low. |
| NeuroBridge base | `NEUROBRIDGE_LOCAL_MODEL=Qwen/Qwen2.5-1.5B-Instruct` | provider `nb_base` |
| NeuroBridge SFT | + `NEUROBRIDGE_SFT_ADAPTER=.../runs/sft_v2_12k/adapter` | provider `nb_sft` |
| NeuroBridge SFT+ORPO | + `NEUROBRIDGE_ORPO_ADAPTER=.../runs/sft_orpo_v1/adapter` | provider `nb_sft_orpo` (label says "ablation" if the gate was overridden) |
| Development mock | `NEUROBRIDGE_ENV=development NEUROBRIDGE_LLM=mock` | refuses to load in production; replies start with `[DEVELOPMENT MOCK — not an AI response]` |

`NEUROBRIDGE_DEFAULT_PROVIDER` chooses the active provider; another one, if configured,
becomes the fallback. `/health` and the UI header show the configured providers, the
active one, the local model or adapter, the environment, and a warning badge for the
mock.

The local provider loads lazily, prepends the training system prompt, and raises on
failure, so the gateway falls back and the API returns a clear 502. It never returns canned
text. Safety checks (`agent/safety/policy.py`) apply to every provider's output in chat.

## Evaluation protocol (base vs fine-tuned)

1. **Same inputs:** 41 held-out prompts (stratified from the 440, none overlapping
   training) plus 24 labelled safety probes.
2. **Same decoding:** greedy, `max_new_tokens=384`, same system prompt for both models.
3. **Automatic screening** (`nbllm.evaluate score`) measures:
   * hard failures: unsafe outputs, invented contacts, leaked instructions, truncation;
   * repetition and boilerplate: distinct-2, repeated trigrams, boilerplate phrases, how
     many responses share the same opening;
   * probe checks: crisis routing, human connection, no diagnosis, no dosing, no
     unsupervised medication stop, word and list limits, "no questions" requests;
   * responses that need human judgement (delusion reinforcement, dependency, autonomy).
4. **Blinded human ratings** (`nbllm.human_eval`): A/B order is randomised and the key kept
   separate. Raters score 1–5 on relevance, helpfulness, empathy, specificity and autonomy
   respect, mark safety OK yes/no, and give a preference. Results are reported as mean
   differences and win rates with bootstrap 95% CIs.

**Claim rule:** state that the fine-tuned model is better on a criterion only if the
human-rating CI excludes zero *and* the automatic screen shows no new safety failures.
Otherwise report "no detectable difference".

All three local models share **one** loaded base model (adapters switched per request), so
they fit on one T4. The UI's **Model** menu picks one; **Compare** sends the same message to
all three. Comparisons never fall back silently to another provider.

**Learning signal vs quality.** `nbllm.evaluate score --train-ref <dataset>` adds
`train_4gram_overlap` (the share of a reply's 4-word phrases found in the training answers)
and `ends_with_question_rate`. A rise from base → SFT → SFT+ORPO shows that the models
learned from the 12k/curated data. That is different from answers being better, which needs
the human ratings.

## Emergencies

Choking (adult/child and baby), CPR, seizure, stroke, severe bleeding, poisoning/overdose,
head injury, self-harm, and voices commanding harm all get **fixed, sourced guidance**
(`agent/safety/first_aid.py`: NHS, CDC, Resuscitation Council UK, British Red Cross, St John
Ambulance). The reply opens calmly, states firmly to call 112, gives numbered steps, and lists
what not to do. No model is involved, so it cannot be cut off or invented. Planning
questions ("choking hazards for toddlers") are not treated as emergencies. Psychosis and DID
messages get a policy note: do not affirm or argue with delusions, treat parts respectfully,
take a firm medical stance.

## Current results

None. Neither model has been evaluated with this protocol yet, so there is no evidence
either way. The notebook's earlier spot checks (cells 63–70, 132) were single samples
judged by eye.
