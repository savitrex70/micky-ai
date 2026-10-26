# Task 240 — Clinical Workflow Boundary Verification

**Repository:** savitrex70/micky-ai  
**Branch policy:** main only  
**Scope:** verify integration with the existing deterministic, fully audited ROP reasoning API without blending clinical records into personal conversation/workspace data.

## Added automated coverage

`tests/test_stage9_clinical_integration.py` runs an in-process API workflow against an isolated SQLite test database:
1. Create a personal assistant conversation through its API.
2. Create a clinical reasoning session with a unique clinical-only marker.
3. Add a clinical observation to that session.
4. Execute the existing `/sessions/{session_id}/reasoning-run/execute-fully-audited` endpoint and validate the result package shape and session identity.
5. Try the personal conversation UUID against the clinical endpoint and require a 404.
6. Export general personal data and prove the export contains only the allowed conversation domain, not the clinical marker.
7. Check the served UI contains the separate clinical panel, renders the audited package as text, and displays the disclaimer that the workflow is not a validated diagnosis or treatment recommendation.

The test exercises real route/service code in-process; it does not substitute for PostgreSQL migration tests, the real browser flow, nor clinical-validity review.

## Boundary and safety decision

Stage 9.6 reuses the repository's audited reasoning-run API. No free-form clinical chatbot, model/provider, hosted API, Ollama integration, or new clinical decision logic has been added. Package consistency is not clinical validity. Clinical-session identifiers remain separate from assistant conversation identifiers. The clinical-only data is deliberately not part of the new general personal-data export.

## Verification status

The automated test is committed with the implementation. Acceptance depends on the current main CI run passing with the PostgreSQL service enabled. A manual local browser walkthrough has not been performed here and is not claimed. Keep Stage 9 open until Task 242's final acceptance evidence and the user's local validation are complete.
