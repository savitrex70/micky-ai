"""Task 207 authorized dataset preparation tests; no model, network, or data."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
    DATASET_MANIFEST_CONTRACT_VERSION,
    RECORDS_FINGERPRINT_SCHEME_VERSION,
    AuthorizationStatus,
    DatasetManifest,
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


# --- Task 207 correction: record-set fingerprints ---------------------------

from rop.dataset_preparation import (  # noqa: E402
    FINGERPRINT_SCHEME_VERSION,
    PreparedSplits,
    records_fingerprint,
)


def _fingerprint_of(*records: RawDatasetRecord) -> str:
    return records_fingerprint(tuple(records))


def test_fingerprint_is_deterministic_and_order_independent() -> None:
    records = _records(12)
    assert records_fingerprint(records) == records_fingerprint(records)
    assert records_fingerprint(records) == records_fingerprint(tuple(reversed(records)))
    assert len(records_fingerprint(records)) == 64
    assert FINGERPRINT_SCHEME_VERSION.startswith("records-fingerprint")


def test_fingerprint_changes_when_labels_change() -> None:
    base = _record("r-0", "g-0", "content 0")
    relabeled = _record("r-0", "g-0", "content 0", labels=("POTASSIUM_HIGH",))
    assert _fingerprint_of(base) != _fingerprint_of(relabeled)


def test_fingerprint_changes_when_the_group_key_changes() -> None:
    base = _record("r-0", "g-0", "content 0")
    regrouped = _record("r-0", "g-1", "content 0")
    assert _fingerprint_of(base) != _fingerprint_of(regrouped)


def test_fingerprint_changes_with_privacy_status_id_and_content() -> None:
    base = _record("r-0", "g-0", "content 0")
    assert _fingerprint_of(base) != _fingerprint_of(
        _record("r-0", "g-0", "content 0", privacy_safe=False)
    )
    assert _fingerprint_of(base) != _fingerprint_of(_record("r-9", "g-0", "content 0"))
    assert _fingerprint_of(base) != _fingerprint_of(_record("r-0", "g-0", "content 1"))


def test_fingerprint_encoding_has_unambiguous_field_boundaries() -> None:
    # Plain concatenation would make these collide ("ab"+"c" vs "a"+"bc").
    first = _record("ab", "c", "content 0")
    second = _record("a", "bc", "content 0")
    assert _fingerprint_of(first) != _fingerprint_of(second)
    # Label boundaries: ("A", "BC") must differ from ("AB", "C").
    left = _record("r-0", "g-0", "content 0", labels=("A", "BC"))
    right = _record("r-0", "g-0", "content 0", labels=("AB", "C"))
    assert _fingerprint_of(left) != _fingerprint_of(right)


def test_fingerprint_distinguishes_record_set_shapes() -> None:
    one = _record("r-0", "g-0", "content 0")
    two = _record("r-1", "g-0", "content 1")
    assert _fingerprint_of(one, two) != _fingerprint_of(one)
    assert _fingerprint_of() != _fingerprint_of(one)


def test_manifest_fingerprints_follow_the_effective_data() -> None:
    kwargs = dict(
        dataset_id="dataset-1",
        schema_version="schema-1",
        label_space_version="labels-1",
        source=_source(),
        label_space=LABEL_SPACE,
        authorization_evidence_reference=AUTH_REF,
    )
    records = _records(12)
    splits = assign_group_safe_splits(records, train_ratio=0.5, validation_ratio=0.25)
    original = build_manifest(splits=splits, **kwargs)

    victim = splits.train[0]
    relabeled = victim.model_copy(update={"labels": ("POTASSIUM_HIGH",)})
    changed_labels = PreparedSplits(
        train=(relabeled, *splits.train[1:]),
        validation=splits.validation,
        test=splits.test,
    )
    after_labels = build_manifest(splits=changed_labels, **kwargs)
    assert after_labels.dataset_fingerprint != original.dataset_fingerprint
    assert (
        dict(after_labels.split_fingerprints)["train"]
        != dict(original.split_fingerprints)["train"]
    )
    assert (
        dict(after_labels.split_fingerprints)["test"]
        == dict(original.split_fingerprints)["test"]
    )

    # Renaming a group everywhere (kept disjoint) must also be visible.
    renamed_train = tuple(
        (
            record.model_copy(update={"group_key": f"renamed-{record.group_key}"})
            if record.group_key == victim.group_key
            else record
        )
        for record in splits.train
    )
    after_group = build_manifest(
        splits=PreparedSplits(
            train=renamed_train, validation=splits.validation, test=splits.test
        ),
        **kwargs,
    )
    assert after_group.dataset_fingerprint != original.dataset_fingerprint


def test_manifest_contains_no_raw_ids_or_group_keys() -> None:
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
    dumped = manifest.model_dump_json()
    assert "group-0" not in dumped
    assert "r-0-0" not in dumped


# --- Task 207 correction: false-clean deduplication -------------------------


def test_duplicate_content_with_identical_labels_collapses_deterministically() -> None:
    first = _record("r-1", "g-0", "same content")
    second = _record("r-0", "g-0", "SAME  content")
    forward = exact_deduplicate((first, second))
    reverse = exact_deduplicate((second, first))
    assert forward == reverse
    assert [record.record_id for record in forward] == ["r-0"]


def test_duplicate_content_with_conflicting_labels_fails_closed() -> None:
    first = _record("r-0", "g-0", "same content", labels=("ANION_GAP_HIGH",))
    second = _record("r-1", "g-0", "Same Content", labels=("POTASSIUM_HIGH",))
    for ordering in ((first, second), (second, first)):
        with pytest.raises(DatasetPreparationError) as caught:
            exact_deduplicate(ordering)
        assert (
            caught.value.code is DatasetRejectionCode.DUPLICATE_CONTENT_LABEL_CONFLICT
        )
        assert "r-0" not in str(caught.value)
        assert "g-0" not in str(caught.value)


def test_conflict_is_detected_even_when_a_third_duplicate_agrees() -> None:
    agree_one = _record("r-0", "g-0", "same content", labels=("ANION_GAP_HIGH",))
    agree_two = _record("r-1", "g-0", "same content", labels=("ANION_GAP_HIGH",))
    disagree = _record("r-2", "g-0", "same content", labels=("POTASSIUM_HIGH",))
    with pytest.raises(DatasetPreparationError) as caught:
        exact_deduplicate((agree_one, agree_two, disagree))
    assert caught.value.code is DatasetRejectionCode.DUPLICATE_CONTENT_LABEL_CONFLICT


def test_duplicates_with_varying_group_keys_keep_one_record_deterministically() -> None:
    first = _record("r-1", "group-b", "shared content")
    second = _record("r-0", "group-a", "shared content")
    distinct = _record("r-2", "group-b", "other content")
    kept = exact_deduplicate((first, second, distinct))
    assert [(r.record_id, r.group_key) for r in kept] == [
        ("r-0", "group-a"),
        ("r-2", "group-b"),
    ]
    assert exact_deduplicate((distinct, second, first)) == kept


def test_conflicting_labels_with_varying_groups_still_fail_closed() -> None:
    first = _record("r-0", "group-a", "shared", labels=("ANION_GAP_HIGH",))
    second = _record("r-1", "group-b", "shared", labels=("POTASSIUM_HIGH",))
    with pytest.raises(DatasetPreparationError) as caught:
        exact_deduplicate((first, second))
    assert caught.value.code is DatasetRejectionCode.DUPLICATE_CONTENT_LABEL_CONFLICT


# --- Task 207 correction: manifest verifies split integrity -----------------

MANIFEST_KWARGS = dict(
    dataset_id="dataset-1",
    schema_version="schema-1",
    label_space_version="labels-1",
    label_space=LABEL_SPACE,
    authorization_evidence_reference=AUTH_REF,
)


def _manifest_for(splits: PreparedSplits, **patch: object):
    kwargs = {**MANIFEST_KWARGS, "source": _source(), **patch}
    return build_manifest(splits=splits, **kwargs)


def _expect_code(splits: PreparedSplits, code: DatasetRejectionCode, **patch) -> None:
    with pytest.raises(DatasetPreparationError) as caught:
        _manifest_for(splits, **patch)
    assert caught.value.code is code


def test_valid_splits_still_build_a_manifest() -> None:
    splits = assign_group_safe_splits(
        _records(12), train_ratio=0.5, validation_ratio=0.25
    )
    assert _manifest_for(splits).dataset_id == "dataset-1"


def test_duplicate_record_ids_across_splits_are_rejected() -> None:
    train = _record("r-0", "group-a", "content a")
    test = _record("r-0", "group-b", "content b")
    _expect_code(
        PreparedSplits(train=(train,), validation=(), test=(test,)),
        DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
    )


def test_duplicate_record_ids_within_a_split_are_rejected() -> None:
    first = _record("r-0", "group-a", "content a")
    second = _record("r-0", "group-a", "content b")
    _expect_code(
        PreparedSplits(train=(first, second), validation=(), test=()),
        DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
    )


def test_identical_content_in_different_splits_is_rejected() -> None:
    train = _record("r-0", "group-a", "shared content")
    test = _record("r-1", "group-b", "Shared   Content")
    _expect_code(
        PreparedSplits(train=(train,), validation=(), test=(test,)),
        DatasetRejectionCode.CONTENT_CROSS_SPLIT,
    )


def test_conflicting_labels_for_identical_content_are_rejected() -> None:
    first = _record("r-0", "group-a", "shared", labels=("ANION_GAP_HIGH",))
    second = _record("r-1", "group-a", "shared", labels=("POTASSIUM_HIGH",))
    _expect_code(
        PreparedSplits(train=(first, second), validation=(), test=()),
        DatasetRejectionCode.DUPLICATE_CONTENT_LABEL_CONFLICT,
    )


def test_a_group_spanning_splits_is_rejected() -> None:
    train = _record("r-0", "group-a", "content a")
    validation = _record("r-1", "group-a", "content b")
    _expect_code(
        PreparedSplits(train=(train,), validation=(validation,), test=()),
        DatasetRejectionCode.GROUP_CROSS_SPLIT,
    )


def test_privacy_unsafe_record_is_rejected_at_manifest_time() -> None:
    unsafe = _record("r-0", "group-a", "content a", privacy_safe=False)
    _expect_code(
        PreparedSplits(train=(unsafe,), validation=(), test=()),
        DatasetRejectionCode.PRIVACY_UNSAFE,
    )


def test_label_outside_the_space_is_rejected_at_manifest_time() -> None:
    record = _record("r-0", "group-a", "content a", labels=("UNSUPPORTED_LABEL",))
    _expect_code(
        PreparedSplits(train=(record,), validation=(), test=()),
        DatasetRejectionCode.LABEL_OUT_OF_SPACE,
    )


def test_malformed_records_are_rejected_even_when_validation_was_bypassed() -> None:
    malformed = RawDatasetRecord.model_construct(
        record_id="r-0",
        group_key="group-a",
        content_fingerprint="not-a-fingerprint",
        labels=("ANION_GAP_HIGH",),
        privacy_safe=True,
    )
    _expect_code(
        PreparedSplits(train=(malformed,), validation=(), test=()),
        DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
    )
    _expect_code(
        PreparedSplits(train=("not-a-record",), validation=(), test=()),  # type: ignore[arg-type]
        DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
    )


def test_a_repeated_label_in_the_label_space_is_rejected() -> None:
    splits = assign_group_safe_splits(
        _records(12), train_ratio=0.5, validation_ratio=0.25
    )
    with pytest.raises(DatasetPreparationError) as caught:
        build_manifest(
            **{**MANIFEST_KWARGS, "label_space": ("ANION_GAP_HIGH", "ANION_GAP_HIGH")},
            source=_source(),
            splits=splits,
        )
    assert caught.value.code is DatasetRejectionCode.RECORD_STRUCTURE_INVALID


def test_integrity_errors_never_expose_ids_groups_or_content() -> None:
    train = _record("secret-record", "secret-group", "secret content")
    test = _record("other-record", "other-group", "secret content")
    with pytest.raises(DatasetPreparationError) as caught:
        _manifest_for(PreparedSplits(train=(train,), validation=(), test=(test,)))
    message = str(caught.value)
    for sensitive in ("secret-record", "secret-group", "secret content", "other-"):
        assert sensitive not in message


@pytest.mark.parametrize(
    "authorization", [AuthorizationStatus.UNKNOWN, AuthorizationStatus.REVOKED]
)
def test_unknown_or_revoked_sources_never_become_training_approval(
    authorization: AuthorizationStatus,
) -> None:
    splits = assign_group_safe_splits(
        _records(12), train_ratio=0.5, validation_ratio=0.25
    )
    with pytest.raises(Exception, match="blocked"):
        _manifest_for(splits, source=_source(authorization=authorization))
    manifest = _manifest_for(
        splits,
        source=_source(authorization=authorization),
        training_blocked_reason="authorization is not confirmed",
    )
    assert manifest.training_blocked_reason is not None
    with pytest.raises(DatasetPreparationError):
        require_authorized_source(
            _source(authorization=authorization), PermittedPurpose.TRAINING
        )


# --- Task 207 correction: scheme provenance, deduplication, label validity --


def _valid_manifest():
    splits = assign_group_safe_splits(
        _records(12), train_ratio=0.5, validation_ratio=0.25
    )
    return _manifest_for(splits)


def test_manifest_persists_the_fingerprint_scheme_and_contract_version() -> None:
    from rop.dataset_preparation import FINGERPRINT_SCHEME_VERSION

    manifest = _valid_manifest()
    assert manifest.fingerprint_scheme_version == "records-fingerprint-v2"
    assert manifest.fingerprint_scheme_version == FINGERPRINT_SCHEME_VERSION
    assert RECORDS_FINGERPRINT_SCHEME_VERSION == FINGERPRINT_SCHEME_VERSION
    assert manifest.contract_version == DATASET_MANIFEST_CONTRACT_VERSION == "2"
    dumped = manifest.model_dump(mode="json")
    assert dumped["fingerprint_scheme_version"] == "records-fingerprint-v2"
    assert DatasetManifest.model_validate(dumped) == manifest


def test_manifest_rejects_a_mismatched_or_missing_fingerprint_scheme() -> None:
    dumped = _valid_manifest().model_dump(mode="json")
    for bad in ("records-fingerprint-v1", "records-fingerprint-v3", ""):
        with pytest.raises(ValidationError):
            DatasetManifest.model_validate(
                {**dumped, "fingerprint_scheme_version": bad}
            )
    without_scheme = {
        key: value
        for key, value in dumped.items()
        if key != "fingerprint_scheme_version"
    }
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(without_scheme)


def test_manifest_rejects_the_previous_contract_version() -> None:
    dumped = _valid_manifest().model_dump(mode="json")
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate({**dumped, "contract_version": "1"})


def test_fingerprints_stay_deterministic_for_valid_deduplicated_input() -> None:
    first = _valid_manifest()
    second = _valid_manifest()
    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert first.split_fingerprints == second.split_fingerprints
    assert first == second


def test_identical_content_in_one_split_is_rejected_with_its_own_code() -> None:
    first = _record("r-0", "group-a", "shared content")
    second = _record("r-1", "group-a", "Shared   Content")
    assert first.labels == second.labels
    _expect_code(
        PreparedSplits(train=(first, second), validation=(), test=()),
        DatasetRejectionCode.DUPLICATE_CONTENT_IN_SPLIT,
    )
    # Also when the duplicate sits in a different group of the same split.
    third = _record("r-2", "group-b", "shared content")
    _expect_code(
        PreparedSplits(train=(first, third), validation=(), test=()),
        DatasetRejectionCode.DUPLICATE_CONTENT_IN_SPLIT,
    )


def test_duplicate_error_codes_stay_distinct() -> None:
    same_split = DatasetRejectionCode.DUPLICATE_CONTENT_IN_SPLIT
    cross_split = DatasetRejectionCode.CONTENT_CROSS_SPLIT
    conflict = DatasetRejectionCode.DUPLICATE_CONTENT_LABEL_CONFLICT
    assert len({same_split, cross_split, conflict}) == 3
    a = _record("r-0", "group-a", "shared")
    b = _record("r-1", "group-b", "shared")
    _expect_code(PreparedSplits(train=(a,), validation=(), test=(b,)), cross_split)
    c = _record("r-2", "group-a", "shared", labels=("POTASSIUM_HIGH",))
    _expect_code(PreparedSplits(train=(a, c), validation=(), test=()), conflict)


def test_same_split_duplicate_message_is_safe() -> None:
    first = _record("secret-record", "secret-group", "secret content")
    second = _record("other-record", "secret-group", "secret content")
    with pytest.raises(DatasetPreparationError) as caught:
        _manifest_for(PreparedSplits(train=(first, second), validation=(), test=()))
    message = str(caught.value)
    for sensitive in ("secret-record", "secret-group", "secret content", "other-"):
        assert sensitive not in message


def test_deduplicated_input_builds_a_manifest_after_manual_duplicates_fail() -> None:
    records = (
        _record("r-0", "group-a", "shared"),
        _record("r-1", "group-a", "shared"),
        _record("r-2", "group-b", "unique"),
    )
    with pytest.raises(DatasetPreparationError):
        _manifest_for(PreparedSplits(train=records, validation=(), test=()))
    deduplicated = exact_deduplicate(records)
    manifest = _manifest_for(PreparedSplits(train=deduplicated, validation=(), test=()))
    assert manifest.train_counts.record_count == 2


@pytest.mark.parametrize("blank", ["", " ", "   ", "\t", "\u00a0"])
def test_blank_record_labels_are_rejected(blank: str) -> None:
    with pytest.raises(ValidationError):
        _record("r-0", "group-a", "content", labels=(blank,))
    with pytest.raises(ValidationError):
        _record("r-0", "group-a", "content", labels=("ANION_GAP_HIGH", blank))


@pytest.mark.parametrize(
    "bad_space",
    [
        (),
        ("ANION_GAP_HIGH", "ANION_GAP_HIGH"),
        ("POTASSIUM_HIGH", "ANION_GAP_HIGH"),
        ("ANION_GAP_HIGH", " "),
        ("", "ANION_GAP_HIGH"),
    ],
)
def test_malformed_label_spaces_are_rejected_by_every_entry_point(
    bad_space: tuple[str, ...],
) -> None:
    splits = assign_group_safe_splits(
        _records(12), train_ratio=0.5, validation_ratio=0.25
    )
    with pytest.raises(DatasetPreparationError) as built:
        build_manifest(
            **{**MANIFEST_KWARGS, "label_space": bad_space},
            source=_source(),
            splits=splits,
        )
    assert built.value.code is DatasetRejectionCode.RECORD_STRUCTURE_INVALID
    with pytest.raises(DatasetPreparationError) as validated:
        validate_records(_records(12)[:1], bad_space)
    assert validated.value.code is DatasetRejectionCode.RECORD_STRUCTURE_INVALID


def test_label_space_error_message_does_not_echo_labels() -> None:
    with pytest.raises(DatasetPreparationError) as caught:
        validate_records(_records(12)[:1], ("secret-label", "secret-label"))
    assert "secret-label" not in str(caught.value)


def test_manifest_contract_rejects_malformed_label_distribution() -> None:
    dumped = _valid_manifest().model_dump(mode="json")
    for bad in (
        [],
        [["ANION_GAP_HIGH", 1], ["ANION_GAP_HIGH", 1]],
        [["POTASSIUM_HIGH", 1], ["ANION_GAP_HIGH", 1]],
        [["ANION_GAP_HIGH", 1], [" ", 0]],
        [["", 0]],
    ):
        with pytest.raises(ValidationError):
            DatasetManifest.model_validate({**dumped, "label_distribution": bad})


def test_validate_label_space_helper_accepts_a_canonical_space() -> None:
    from rop.schemas.dataset_manifest import validate_label_space

    assert validate_label_space(LABEL_SPACE) == LABEL_SPACE
