"""Canonical Stage 7 upstream source constants (Tasks 162, 163 and 164).

These three string constants identify the approved producers of the Stage 7
audit package, vertical slice and vertical-slice audit. The Task 165, 166 and
168 contracts must recognize them, and the Task 162-164 services must publish
them. Defining them here, in a module with no imports, lets both layers depend
on one definition: the schemas never import a service, and each service
re-exports its own constant under the same name so existing imports of it from
the service module keep working.
"""

REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162 = (
    "REASONING_RUN_STAGE_7_AUDIT_PACKAGE_TASK_162"
)

REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163 = (
    "REASONING_RUN_STAGE_7_VERTICAL_SLICE_TASK_163"
)

REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164 = (
    "REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_TASK_164"
)
