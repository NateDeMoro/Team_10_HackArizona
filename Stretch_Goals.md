# Gemma 4 Stretch Goals — Nuclear Cooling-Water Derating Forecaster

Ranked by build cost vs. demo impact. All assume Gemma 4 E4B via Ollama (runs on a laptop, no API key, no rate limits — important for a 36hr demo).

## 1. Operator Briefing Endpoint — `GET /plants/{id}/briefing` (highest ROI, ~2 hrs)

Take the 14-day forecast + top-5 SHAP features + current weather, prompt Gemma 4 for a 3-sentence shift-handoff summary. Render at the top of the plant detail page.

- **Why it lands:** instantly demoable, makes the numeric output feel human, hits the "AI for operators" narrative.
- **Build:** `ollama serve` running gemma3:4b (or gemma 4 when available locally), small FastAPI route, structured-output prompt with the forecast JSON inlined.
- **Cache** the briefing keyed on (plant_id, run_date) — regenerate daily, not per request.

## 2. "Ask the Forecast" Chat Panel (~4 hrs)

Sidebar on the plant detail page. Operator types questions; Gemma 4 with **function calling** invokes existing endpoints.

- Tools to expose: `get_forecast`, `get_backtest(as_of)`, `get_shap(horizon)`, `get_weather_window`.
- Killer questions to seed: *"Why did the band widen on Day 7?"*, *"How did we do on the July 2024 heatwave?"*, *"Which feature is driving the Day 3 dip?"*
- **Why it lands:** judges can interact with it live. Function calling = clear "agentic AI" story.

## 3. Counterfactual Sensitivity ("What If") Mode (~3 hrs)

UI sliders for streamflow, wet-bulb, intake temp. Re-run inference on perturbed features; Gemma 4 narrates the delta in natural language.

- **Why it lands:** turns the model into a planning tool, not just a prediction. Operators care about "what if the heatwave is 2°F worse than NWP says."
- Reuses the chat panel's tool-calling plumbing.

## 4. NWP Forecast Discussion Parser (~2 hrs)

Pull NWS Area Forecast Discussions (free text, issued 2x/day per region). Have Gemma 4 extract structured signals (heat dome mentions, drought language, frontal passage timing) and surface them as soft "context flags" alongside the numeric forecast.

- **Why it lands:** uses Gemma's text understanding for something XGBoost genuinely can't do — qualitative meteorologist intent.

## 5. Multimodal Radar/Satellite Read (~4 hrs, higher risk)

Feed NOAA radar mosaic images of the upper Mississippi basin to Gemma 4 vision. Ask it to flag upstream convection that hasn't yet shown up in streamflow gauges (rainfall takes hours-to-days to propagate downstream).

- **Why it lands:** vision modality is the most novel use of Gemma 4. Differentiator if other teams stick to text.
- **Risk:** prompt engineering for reliable extraction takes time; have a fallback if it hallucinates.

## 6. SHAP-to-Story Translator (~1 hr, bundle with #1)

Replace the bare SHAP feature-name + value table with a Gemma-rewritten causal sentence. Ship as part of #1's prompt rather than a separate feature.

---

## Recommended order if time-boxed

- **Must-do:** #1 + #6 (one prompt, two surface areas).
- **Should-do:** #2 (sells the "agent" angle).
- **Stretch if #2 lands fast:** #3 or #4.
- **Skip #5** unless someone on the team has multimodal-prompting experience already.

## Implementation note

Wrap all Gemma calls behind a single `llm_client.py` with a `MOCK=true` fallback that returns canned strings. Demo day comes; if Ollama hangs, flip an env var and the UI still works.
