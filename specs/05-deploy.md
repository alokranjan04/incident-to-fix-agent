# 05 · Deploy and integrate

1. Deploy the agent: `adk deploy agent_engine` (Agent Runtime) or `adk deploy cloud_run`.
2. Service account: Secret Manager Secret Accessor, Vertex AI User, Cloud Build Editor,
   Cloud Trace Agent. Nothing broader.
3. Trigger: a ServiceNow Flow Designer flow on new incidents with category
   `software_defect` calls the Cloud Run endpoint with a bearer token.
4. Stretch: expose the agent over A2A and register it in ServiceNow AI Agent Orchestrator.
5. Install the Gemini Code Assist GitHub app on the target repo for automated PR review.
6. Add secret scanning and a dependency scan to the target repo's CI.

Acceptance criteria
- WHEN a new `software_defect` incident is created in ServiceNow, a PR SHALL be opened (or a
  work note added explaining why not) without any manual step.
- Every run SHALL produce one trace in Cloud Trace with per-step latency, tokens and cost.
