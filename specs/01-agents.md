# 01 · Agents (Google ADK)

Root agent `incident_to_fix` is a SequentialAgent. Shared ADK session state keys:
`incident`, `branch`, `suspect_files`, `patch`, `test_result`, `review`, `pr_url`.

| Step | Agent | Tools | Writes to state |
| --- | --- | --- | --- |
| 1 | triage | servicenow.get_incident | incident, branch, decision (fix or escalate) |
| 2 | locator | github.search_code, github.get_file_contents, github.list_commits | suspect_files (ranked, with reasons) |
| 3 | fixer | github.get_file_contents | patch (files + new test) |
| 4 | verifier | run_tests (Cloud Build) | test_result |
| 5 | reviewer | none (self-reflection) | review (approve or revise, with reasons) |
| 6 | publisher | github.create_branch, github.push_files, github.create_pull_request, servicenow.add_work_note | pr_url |

Steps 3 to 5 run inside a LoopAgent with max_iterations = 2.

## Acceptance criteria (EARS)
- WHEN an incident has category `software_defect` and `u_repo` on the allow-list, the system
  SHALL start the pipeline for that incident.
- WHEN the incident text names a branch ("branch bug/07"), the system SHALL base the fix on
  that branch; OTHERWISE it SHALL use `main`.
- WHEN triage decides the incident is not a code defect, the system SHALL add a work note
  explaining why and SHALL stop without opening a PR.
- The locator SHALL return at most 3 suspect files, each with a one-line reason.
- The fixer SHALL add or change a test that fails before the fix and passes after it.
- IF tests fail after 2 fix attempts, THEN the system SHALL add a work note with the failing
  output and SHALL NOT open a PR.
- WHEN a PR is opened, the system SHALL put the incident number in the PR title and SHALL add
  the PR URL to the incident's work notes.
