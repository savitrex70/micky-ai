"""Task 207 authorized dataset preparation tests; no model, network, or data."""

from __future__ import annotations

import pytest

from rop.dataset_preparation import (
    DatasetPreparationError,
    assign_group_safe_splits,
    build_manifest,
    content_fingerprint,
    exact_deduplicate,
    fit_transformation_on_train_only,
    normalize_content,
    require_authorized_source,
    validate_records,
)
from rop.schemas.dataset_manifest import (
    AuthorizationStatus,
    DatasetRejectionCode,
    DatasetSourceDescriptor,
    PermittedPurpose,
    RawDatasetRecord,
)

LABEL_SPACE = ("ANION_GAP_HIGH", "POTASSIUM_HIGH")
AUTH_REF = "auth:approval-2026-0001"


def _source(**patch: object) -> DatasetSourceDescriptor:
    value = {
        "source_id": "source-lab-1",
        "authorization": AuthorizationStatus.AUTHORIZED,
        "permitted_purposes": [
            PermittedPurpose.EVALUATION,
            PermittedPurpose.TRAINING,
            PermittedPurpose.VALIDATION,
        ],
        "provenance_reference": "doc:dataset-provenance-1",
        "is_synthetic": False,
    }
    value.update(patch)
    return DatasetSourceDescriptor.model_validate(value)


def _record(
    record_id: str, group_key: str, content: str, **patch: object
) -> RawDatasetRecord:
    value = {
        "record_id": record_id,
        "group_key": group_key,
        "content_fingerprint": content_fingerprint(content),
        "labels": sorted(["ANION_GAP_HIGH"]),
        "privacy_safe": True,
    }
    value.update(patch)
    return RawDatasetRecord.model_validate(value)


def _records(count: int = 12) -> tuple[RawDatasetRecord, ...]:
    # 4 groups x 3 records; each group has distinct content.
    records = []
    for group in range(4):
        for index in range(3):
            records.append(
                _record(
                    record_id=f"r-{group}-{index}",
                    group_key=f"group-{group}",
                    content=f"content {group}-{index}",
                )
            )
    return tuple(records)


# --- authorization gate -----------------------------------------------------


def test_unknown_authorization_is_rejected() -> None:
    source = _source(authorization=AuthorizationStatus.UNKNOWN)
    with pytest.raises(DatasetPreparationError) as caught:
        require_authorized_source(source, PermittedPurpose.TRAINING)
    assert caught.value.code is DatasetRejectionCode.SOURCE_AUTHORIZATION_UNKNOWN


def test_revoked_authorization_is_rejected() -> None:
    source = _source(authorization=AuthorizationStatus.REVOKED)
    with pytest.raises(DatasetPreparationError) as caught:
        require_authorized_source(source, PermittedPurpose.TRAINING)
    assert caught.value.code is DatasetRejectionCode.SOURCE_NOT_AUTHORIZED


def test_unapproved_purpose_is_rejected() -> None:
    source = _source(permitted_purposes=[PermittedPurpose.EVALUATION])
    with pytest.raises(DatasetPreparationError) as caught:
        require_authorized_source(source, PermittedPurpose.TRAINING)
    assert caught.value.code is DatasetRejectionCode.PURPOSE_NOT_APPROVED


def test_authorized_source_passes_for_permitted_purpose() -> None:
    require_authorized_source(_source(), PermittedPurpose.TRAINING)


# --- record validation ------------------------------------------------------


def test_unsafe_privacy_status_is_rejected() -> None:
    record = _record("r-0", "g-0", "content 0", privacy_safe=False)
    with pytest.raises(DatasetPreparationError) as caught:
        validate_records((record,), LABEL_SPACE)
    assert caught.value.code is DatasetRejectionCode.PRIVACY_UNSAFE


def test_label_outside_the_space_is_rejected() -> None:
    record = _record("r-0", "g-0", "content 0", labels=("UNSUPPORTED_LABEL",))
    with pytest.raises(DatasetPreparationError) as caught:
        validate_records((record,), LABEL_SPACE)
    assert caught.value.code is DatasetRejectionCode.LABEL_OUT_OF_SPACE


def test_duplicate_record_identifiers_are_rejected() -> None:
    first = _record("r-0", "g-0", "content 0")
    second = _record("r-0", "g-0", "content 1")
    with pytest.raises(DatasetPreparationError) as caught:
        validate_records((first, second), LABEL_SPACE)
    assert caught.value.code is DatasetRejectionCode.RECORD_STRUCTURE_INVALID


def test_valid_records_pass_validation() -> None:
    records = validate_records(_records(12)[:3], LABEL_SPACE)
    assert len(records) == 3


# --- normalization and deduplication ----------------------------------------


def test_normalization_is_deterministic_and_canonical() -> None:
    # NFKC composes the ligature; casefold folds case; spaces collapse.
    assert normalize_content("  ﬁle   NAME  ") == normalize_content("file name")
    assert content_fingerprint("Same Content") == content_fingerprint("same   content")


def test_exact_duplicates_keep_the_canonically_first_record() -> None:
    duplicate_one = _record("r-1", "g-0", "same content")
    duplicate_two = _record("r-0", "g-0", "Same  Content")
    distinct = _record("r-2", "g-0", "other content")
    deduplicated = exact_deduplicate((duplicate_one, duplicate_two, distinct))
    assert [record.record_id for record in deduplicated] == ["r-0", "r-2"]


# --- leakage-safe splits -----------------------------------------------------


def test_splits_are_reproducible_and_group_disjoint() -> None:
    records = _records(12)
    first = assign_group_safe_splits(records, train_ratio=0.5, validation_ratio=0.25)
    second = assign_group_safe_splits(records, train_ratio=0.5, validation_ratio=0.25)
    assert first == second
    train_groups = {record.group_key for record in first.train}
    validation_groups = {record.group_key for record in first.validation}
    test_groups = {record.group_key for record in first.test}
    assert not train_groups & validation_groups
    assert not train_groups & test_groups
    assert not validation_groups & test_groups


def test_group_leakage_is_impossible_even_for_split_record_order() -> None:
    records = tuple(reversed(_records(12)))
    splits = assign_group_safe_splits(records, train_ratio=0.5, validation_ratio=0.25)
    for group in {record.group_key for record in splits.all_records()}:
        memberships = sum(
            group in {r.group_key for r in bucket}
            for bucket in (splits.train, splits.validation, splits.test)
        )
        assert memberships == 1


def test_impossible_split_ratios_are_rejected() -> None:
    with pytest.raises(DatasetPreparationError):
        assign_group_safe_splits(_records(3), train_ratio=0.0, validation_ratio=0.5)
    with pytest.raises(DatasetPreparationError):
        assign_group_safe_splits(_records(3), train_ratio=0.8, validation_ratio=0.3)


def test_transformation_fitting_sees_only_the_train_split() -> None:
    splits = assign_group_safe_splits(
        _records(12), train_ratio=0.5, validation_ratio=0.25
    )
    seen: list[int] = []

    def fit(train_records: tuple[RawDatasetRecord, ...]) -> dict[str, int]:
        seen.append(len(train_records))
        return {"count": len(train_records)}

    result = fit_transformation_on_train_only(splits, fit)
    assert result == {"count": len(splits.train)}
    assert seen == [len(splits.train)]


# --- manifest -----------------------------------------------------------------


def test_manifest_records_counts_distribution_and_fingerprints() -> None:
    splits = assign_group_safe_splits(
        _records(12), train_ratio=0.5, validation_ratio=0.25
    )
    manifest = build_manifest(
        dataset_id="dataset-1",
        schema_version="schema-1",
        label_space_version="labels-1",
        source=_source(),
        splits=splits,
        label_space=LABEL_SPACE,
        authorization_evidence_reference=AUTH_REF,
    )
    assert manifest.train_counts.record_count == len(splits.train)
    assert manifest.dataset_fingerprint and len(manifest.dataset_fingerprint) == 64
    assert manifest.training_blocked_reason is None
    assert manifest.label_distribution[0][0] == "ANION_GAP_HIGH"
    assert manifest.split_fingerprints[0][0] == "test"


def test_manifest_is_reproducible_for_identical_inputs() -> None:
    splits = assign_group_safe_splits(
        _records(12), train_ratio=0.5, validation_ratio=0.25
    )
    kwargs = dict(
        dataset_id="dataset-1",
        schema_version="schema-1",
        label_space_version="labels-1",
        source=_source(),
        splits=splits,
        label_space=LABEL_SPACE,
        authorization_evidence_reference=AUTH_REF,
    )
    assert build_manifest(**kwargs) == build_manifest(**kwargs)


def test_manifest_requires_a_blocked_reason_for_unauthorized_sources() -> None:
    splits = assign_group_safe_splits(
        _records(12), train_ratio=0.5, validation_ratio=0.25
    )
    with pytest.raises(Exception, match="blocked"):
        build_manifest(
            dataset_id="dataset-1",
            schema_version="schema-1",
            label_space_version="labels-1",
            source=_source(authorization=AuthorizationStatus.UNKNOWN),
            splits=splits,
            label_space=LABEL_SPACE,
            authorization_evidence_reference=AUTH_REF,
            training_blocked_reason=None,
        )


def test_group_cross_split_detection_fires_on_manually_broken_splits() -> None:
    from rop.dataset_preparation import PreparedSplits

    records = _records(6)
    broken = PreparedSplits(
        train=records[:3],
        validation=records[3:],
        test=records[2:3],  # group-0 leaks into both train and test
    )
    with pytest.raises(DatasetPreparationError) as caught:
        build_manifest(
            dataset_id="dataset-1",
            schema_version="schema-1",
            label_space_version="labels-1",
            source=_source(),
            splits=broken,
            label_space=LABEL_SPACE,
            authorization_evidence_reference=AUTH_REF,
        )
    assert caught.value.code is DatasetRejectionCode.GROUP_CROSS_SPLIT
