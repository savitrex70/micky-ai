# Task 240 — Clinical Workflow Boundary Verification

**Repository:** savitrex70/micky-ai  
**Branch policy:** main only  
**Latest verified code candidate:** 789d771fa4609b5c05091d6773f26fe040c9246d  
**Automated verification:** PASS in [CI run 40360442463](https://github.com/savitrex70/micky-ai/actions/runs/40360442463).

## Automated coverage

`tests/test_stage9_clinical_integration.py` drives the real API in-process against an isolated SQLite test database:
1. Create a personal assistant conversation through its API.
2. Create a separate clinical reasoning session with a unique clinical-only marker.
3. Add an observation to that session.
4. Execute `/sessions/{session_id}/reasoning-run/execute-fully-audited` and validate the result package shape and session identity.
5. Try the personal conversation UUID against the clinical endpoint and require a 404.
6. Export general personal data and prove the clinical-only marker is absent.
7. Check the separate clinical panel, text-only package rendering and disclaimer that package consistency is not a validated diagnosis or treatment recommendation.

The same work fixed six browser clinical-session URL references to match the router mounted at `/sessions`; the Node UI harness and contract path were aligned too. The current green full CI run covers these changes.

## Boundary and safety decision

Stage 9.6 reuses the existing audited deterministic ROP reasoning API. No free-form clinical chatbot, hosted API, Ollama integration, new clinical decision logic or model/provider was added. Clinical-session IDs remain separate from assistant conversation IDs. Clinical data is deliberately excluded from the general personal-data export.

## Remaining acceptance

The API integration test does not substitute for a real browser walkthrough or clinical-validity review. A manual local browser walkthrough has not been performed here. Keep Stage 9 open until the Windows clinical panel is exercised end to end and Task 242's remaining target-machine gates are resolved.
