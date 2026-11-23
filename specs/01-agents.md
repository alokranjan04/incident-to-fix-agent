# 01 · Agents (Google ADK)

Root agent `incident_to_fix` is a SequentialAgent. Shared ADK session state keys:
`incident`, `branch`, `suspect_files`, `patch`, `test_result`, `review`, `pr_url`,
`stop_reason` (`budget`, `escalate` or `tests_failed`; the first reason recorded wins).
These keys and the tool-call counter are per run: they are reset at the start of every run,
so several incidents can be handled in one session.

| Step | Agent | Tools | Writes to state |
| --- | --- | --- | --- |
| 1 | triage | servicenow.get_incident | incident, branch, decision (fix or escalate) |
| 2 | locator | github.search_code, github.get_file_contents, github.list_commits | suspect_files (ranked, with reasons) |
| 3 | fixer | github.get_file_contents | patch (files + new test) |
| 4 | verifier | run_tests (Cloud Build) | test_result |
| 5 | reviewer | none (self-reflection) | review (approve or revise, with reasons) |
| 6 | publisher | github.create_branch, github.push_files, github.create_pull_request, github.list_pull_requests, servicenow.add_work_note (GitHub REST `POST /pulls` as a last resort) | pr_url |

Steps 3 to 5 run inside a LoopAgent with max_iterations = 2.

## Acceptance criteria (EARS)
- WHEN an incident has category `software_defect` and `u_repo` on the allow-list, the system
  SHALL start the pipeline for that incident.
- WHEN the incident text names a branch ("branch bug/07"), the system SHALL base the fix on
  that branch; OTHERWISE it SHALL use `main`.
- WHEN triage decides the incident is not a code defect, the system SHALL add a work note
  explaining why and SHALL stop without opening a PR.
- The locator SHALL return at most 3 suspect files, each with a one-line reason.
- The locator SHALL rank only non-test source files; the reason SHALL name related tests.
- WHEN `get_file_contents` is called again with the same path and ref in a session, the
  system SHALL return the cached result without calling GitHub.
- The fixer SHALL add or change a test that fails before the fix and passes after it.
- IF tests fail after 2 fix attempts, THEN the system SHALL add a work note with the failing
  output and SHALL NOT open a PR.
- WHEN a PR is opened, the system SHALL put the incident number in the PR title and SHALL add
  the PR URL to the incident's work notes.
- WHEN a PR is opened, the system SHALL push to branch `fix/<incident number>` created from the
  incident's branch, and SHALL open the PR against that branch.
- WHEN `fix/<incident number>` already exists, the publisher SHALL reuse it.
- IF `create_pull_request` fails or its response cannot be read, THEN the publisher SHALL
  check with `list_pull_requests` for an open PR from `fix/<incident number>` and use it;
  IF none is found, THEN it SHALL create the PR with the GitHub REST API under the same
  guardrails; IF that fails too, THEN it SHALL add a work note listing each attempt.
- WHEN the run stops early (`stop_reason` is set), every remaining agent SHALL end without
  error (agents with an output schema return schema-valid empty output), and the publisher
  SHALL add exactly one work note explaining why the run stopped.
- No exception from a tool, a model response or the publisher SHALL reach the runner.
