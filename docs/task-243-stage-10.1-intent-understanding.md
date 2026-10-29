# Task 243 — Deterministic Natural-Language Intent Interpretation

Repository: savitrex70/micky-ai
Starting revision: 0091815be0733c299468ded38db147d53c4eac38

## Implementation

Added src/rop/capabilities/intent_interpreter.py. It recognizes a narrow, explicit grammar for help, listing notes/tasks/reminders, searching explicitly authorized local files, creating notes/tasks, and creating reminders. It translates requests to the existing workspace command grammar; the existing parser, authorization policy, confirmation flow, and executor remain authoritative.

The interpreter performs no execution and grants no permission. Unsupported requests remain unsupported. Conflicting intent markers return a safe non-success response rather than choosing an arbitrary action. Extracted fields reject command separators and control characters.

Relative reminder phrases (today, tomorrow, tonight/this evening, and next
week) are returned as structured date-hint metadata, not appended to the
reminder title. The assistant passes that metadata into the existing
server-owned clarification record. Today/tomorrow/tonight require an explicit
local clock time and IANA timezone before the date is resolved; next week
requires an exact date/time and timezone because the phrase does not identify
a particular day. Invalid timezone names, past times, and nonexistent or
ambiguous daylight-saving wall times remain clarification errors. The
existing authorization and confirmation path still gates every write.


## Test coverage

tests/test_intent_interpreter.py contains supported examples, unsupported near misses, conflicting actions, separator injection, and explicit-command compatibility. tests/test_assistant_api.py checks the API routing boundary.

## Limits

This is deterministic pattern recognition, not general language understanding. Relative reminder dates are not silently resolved using the host clock; the existing parser requests sufficient exact date/time and timezone information. Multi-operation workflows are separate Stage 10.4 work.
