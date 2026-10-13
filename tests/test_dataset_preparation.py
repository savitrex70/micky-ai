"""Task 207: dataset-governance preparation tests.

Synthetic-only fixtures with unmistakable synthetic identifiers.
No real data, credentials, network, model, or training.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from rop.dataset_preparation.pipeline import (
    NEAR_DUPLICATE_JACCARD_THRESHOLD,
    DatasetPreparationError,
    check_authorization,
    compose_test_registry,
    dataset_integrity_hash,
    deduplicate_records,
    normalize_content,
    partition_records,
    prepare_dataset,
    validate_record,
    verify_split,
)
from rop.schemas.dataset_authorization import (
    DataSourceAuthorization,
    TrustedSourceRegistry,
)
from rop.schemas.dataset_manifest import SplitConfig

LABELS = ["refutes", "supports"]
PURPOSE = "synthetic-pilot"
AS_OF = "2026-06-01"
GROUPING_UNIT = "synthetic-source-document"
SPLIT = SplitConfig(seed=7, train_ratio=0.6, validation_ratio=0.2, test_ratio=0.2)


def _auth(**overrides):
    base = {
        "source_id": "synthetic-test-source-001",
        "authorization_version": "1.0",
        "origin_description": "synthetic test origin",
        "license_basis": "synthetic-test-only",
        "intended_purpose": PURPOSE,
        "permitted_operations": ["training"],
        "status": "APPROVED",
        "approval_reference": "synthetic-test-approval-001",
    }
    base.update(overrides)
    return base


def _registry(*entries):
    return compose_test_registry(list(entries) if entries else [_auth()])


def _record(
    record_id,
    content="synthetic baseline content",
    label="supports",
    group="synthetic-group-001",
    source="synthetic-test-source-001",
    provenance="synthetic:doc-1",
    **overrides,
):
    base = {
        "record_id": record_id,
        "source_id": source,
        "group_id": group,
        "label": label,
        "content_text": content,
        "provenance_ref": provenance,
    }
    base.update(overrides)
    return base


def _prep(records, registry=None, **overrides):
    params = {
        "records": records,
        "authorizations": (registry if registry is not None else _registry()),
        "dataset_id": "synthetic-dataset-001",
        "purpose": PURPOSE,
        "operation": "training",
        "as_of": AS_OF,
        "allowed_labels": LABELS,
        "grouping_unit": GROUPING_UNIT,
        "split_config": SPLIT,
    }
    params.update(overrides)
    return prepare_dataset(**params)


def _validated(*records):
    registry = _registry()
    return tuple(
        validate_record(
            record,
            allowed_labels=tuple(LABELS),
            authorizations=registry,
            purpose=PURPOSE,
            operation="training",
            as_of=AS_OF,
        )
        for record in records
    )


# --- authorization ---


def test_missing_source_authorization_rejected() -> None:
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(_record("synthetic-rec-001", source="synthetic-test-unknown"))
    assert exc.value.code == "UNKNOWN_SOURCE"
    # End to end, a fully rejected input fails closed at the split
    # stage with a typed error rather than an empty manifest.
    with pytest.raises(DatasetPreparationError) as exc:
        prepare_dataset(
            records=[_record("synthetic-rec-001", source="synthetic-test-unknown")],
            authorizations=_registry(),
            dataset_id="synthetic-dataset-001",
            purpose=PURPOSE,
            operation="training",
            as_of=AS_OF,
            allowed_labels=LABELS,
            grouping_unit=GROUPING_UNIT,
            split_config=SPLIT,
        )
    assert exc.value.code == "INSUFFICIENT_GROUPS"


def test_invalid_approval_reference_rejected() -> None:
    bad = _auth(approval_reference="has space")
    with pytest.raises(DatasetPreparationError) as exc:
        _prep([_record("synthetic-rec-001")], _registry(bad))
    assert exc.value.code == "AUTHORIZATION_INVALID"


def test_purpose_mismatch_rejected() -> None:
    entry = DataSourceAuthorization.model_validate(_auth(intended_purpose="evaluation"))
    with pytest.raises(DatasetPreparationError) as exc:
        check_authorization(
            entry,
            purpose="training",
            operation="training",
            as_of=AS_OF,
        )
    assert exc.value.code == "PURPOSE_MISMATCH"


def test_expiry_revocation_restriction_rejected() -> None:
    expired = DataSourceAuthorization.model_validate(_auth(valid_until="2026-01-01"))
    with pytest.raises(DatasetPreparationError) as exc:
        check_authorization(
            expired,
            purpose=PURPOSE,
            operation="training",
            as_of=AS_OF,
        )
    assert exc.value.code == "AUTHORIZATION_EXPIRED"
    boundary = DataSourceAuthorization.model_validate(_auth(valid_until=AS_OF))
    check_authorization(
        boundary,
        purpose=PURPOSE,
        operation="training",
        as_of=AS_OF,
    )
    revoked = DataSourceAuthorization.model_validate(_auth(status="REVOKED"))
    with pytest.raises(DatasetPreparationError) as exc:
        check_authorization(
            revoked,
            purpose=PURPOSE,
            operation="training",
            as_of=AS_OF,
        )
    assert exc.value.code == "AUTHORIZATION_NOT_APPROVED"
    restricted = DataSourceAuthorization.model_validate(
        _auth(restrictions=["manual release required"])
    )
    with pytest.raises(DatasetPreparationError) as exc:
        check_authorization(
            restricted,
            purpose=PURPOSE,
            operation="training",
            as_of=AS_OF,
        )
    assert exc.value.code == "AUTHORIZATION_RESTRICTED"


def test_caller_boolean_cannot_self_certify() -> None:
    raw = _record("synthetic-rec-001", authorized=True)
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(raw)
    assert exc.value.code == "MALFORMED_RECORD"
    raw = _record("synthetic-rec-001", source="synthetic-test-unknown", authorized=True)
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(raw)
    assert exc.value.code == "UNKNOWN_SOURCE"


def test_fabricated_approval_dictionary_rejected() -> None:
    fabricated = _auth(
        source_id="hospital-real-001",
        approval_reference="real-approval-001",
        license_basis="hospital agreement",
    )
    with pytest.raises(DatasetPreparationError) as exc:
        compose_test_registry([fabricated])
    assert exc.value.code == "TEST_SOURCE_NOT_PERMITTED"
    with pytest.raises(DatasetPreparationError) as exc:
        _prep(
            [_record("synthetic-rec-001", source="hospital-real-001")],
            {"hospital-real-001": fabricated},
        )
    assert exc.value.code == "AUTHORIZATION_INVALID"


def test_bare_schema_instance_is_not_authenticated() -> None:
    entry = DataSourceAuthorization.model_validate(_auth())
    with pytest.raises(DatasetPreparationError) as exc:
        validate_record(
            _record("synthetic-rec-001"),
            allowed_labels=tuple(LABELS),
            authorizations=entry,  # type: ignore[arg-type]
            purpose=PURPOSE,
            operation="training",
            as_of=AS_OF,
        )
    assert exc.value.code == "AUTHORIZATION_INVALID"


def test_test_registry_only_accepts_test_entries() -> None:
    registry = _registry()
    assert isinstance(registry, TrustedSourceRegistry)
    assert registry.registry_kind == "synthetic-test-only"
    with pytest.raises(DatasetPreparationError) as exc:
        compose_test_registry(["not-a-mapping"])  # type: ignore[list-item]
    assert exc.value.code == "AUTHORIZATION_INVALID"


def test_operation_not_permitted_rejected() -> None:
    entry = DataSourceAuthorization.model_validate(
        _auth(permitted_operations=["evaluation"])
    )
    with pytest.raises(DatasetPreparationError) as exc:
        check_authorization(
            entry,
            purpose=PURPOSE,
            operation="training",
            as_of=AS_OF,
        )
    assert exc.value.code == "OPERATION_NOT_PERMITTED"


# --- schema and validation ---


def test_unknown_fields_and_versions_rejected() -> None:
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(_record("synthetic-rec-001", unexpected="x"))
    assert exc.value.code == "MALFORMED_RECORD"
    bad = _auth(authorization_version="2.0")
    with pytest.raises(DatasetPreparationError) as exc:
        _prep([_record("synthetic-rec-001")], _registry(bad))
    assert exc.value.code == "AUTHORIZATION_INVALID"


def test_duplicate_record_ids_rejected() -> None:
    result = _prep(
        [
            _record("synthetic-rec-001", group="synthetic-group-001"),
            _record(
                "synthetic-rec-002",
                content="second content",
                group="synthetic-group-002",
            ),
            _record(
                "synthetic-rec-001",
                content="other content",
                group="synthetic-group-003",
            ),
            _record(
                "synthetic-rec-004",
                content="fourth content",
                group="synthetic-group-004",
            ),
            _record(
                "synthetic-rec-005",
                content="fifth content",
                group="synthetic-group-005",
            ),
        ]
    )
    codes = [entry.code for entry in result.rejections]
    assert "DUPLICATE_RECORD_ID" in codes
    kept = [record.record_id for part in result.partitions for record in part.records]
    assert kept.count("synthetic-rec-001") == 1


def test_missing_and_malformed_binding_identifiers() -> None:
    raw = _record("synthetic-rec-001")
    del raw["group_id"]
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(raw)
    assert exc.value.code == "MISSING_GROUP"
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(_record("synthetic-rec-001", group=""))
    assert exc.value.code == "MISSING_GROUP"
    raw = _record("synthetic-rec-001")
    del raw["provenance_ref"]
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(raw)
    assert exc.value.code == "MISSING_PROVENANCE"
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(_record("synthetic-rec-001", provenance="/etc/shadow"))
    assert exc.value.code == "MALFORMED_RECORD"


def test_invalid_labels_and_corrupt_records() -> None:
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(_record("synthetic-rec-001", label="bogus"))
    assert exc.value.code == "UNSUPPORTED_LABEL"
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(_record("synthetic-rec-001", content=None))
    assert exc.value.code == "MALFORMED_RECORD"
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(_record("synthetic-rec-001", content=""))
    assert exc.value.code == "EMPTY_CONTENT"
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(_record("synthetic-rec-001", content="x" * 2001))
    assert exc.value.code == "OVERSIZED_CONTENT"


def test_deterministic_normalization() -> None:
    assert normalize_content("alpha  beta\tgamma\n delta ") == "alpha beta gamma delta"
    assert normalize_content("ABC") == "ABC"
    assert normalize_content("é") == "é"
    assert normalize_content("é") == normalize_content("é")
    first = _validated(_record("synthetic-rec-001", content="alpha  beta"))
    second = _validated(_record("synthetic-rec-002", content="alpha beta"))
    assert first[0].content_hash == second[0].content_hash


def test_sentinels_never_echoed() -> None:
    credential = "api_key: SENTINEL-SECRET-XYZ-1234567890"
    with pytest.raises(DatasetPreparationError) as exc:
        _validated(_record("synthetic-rec-001", content=f"note {credential}"))
    assert exc.value.code == "PROHIBITED_CONTENT"
    assert "SENTINEL" not in str(exc.value)
    assert "SENTINEL" not in str(exc.value.__cause__)
    benign = _validated(_record("synthetic-rec-002", content="synthetic sentinel note"))
    assert benign[0].content_text == "synthetic sentinel note"
    result = _prep(
        [
            _record("synthetic-rec-001", group="synthetic-group-001"),
            _record(
                "synthetic-rec-002",
                content="second content",
                group="synthetic-group-002",
            ),
            _record(
                "synthetic-rec-003",
                content="note /etc/sentinel-shadow",
                group="synthetic-group-003",
            ),
            _record(
                "synthetic-rec-004",
                content="fourth content",
                group="synthetic-group-004",
            ),
            _record(
                "synthetic-rec-005",
                content="fifth content",
                group="synthetic-group-005",
            ),
        ]
    )
    assert "PROHIBITED_CONTENT" in [entry.code for entry in result.rejections]
    dumped = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    assert "SENTINEL" not in dumped
    assert "sentinel-shadow" not in dumped


# --- deduplication ---


def test_exact_duplicates_keep_first() -> None:
    kept, rejections = deduplicate_records(
        _validated(
            _record("synthetic-rec-002", content="same content here"),
            _record("synthetic-rec-001", content="same content here"),
        )
    )
    assert [record.record_id for record in kept] == ["synthetic-rec-001"]
    assert [(entry.record_id, entry.code) for entry in rejections] == [
        ("synthetic-rec-002", "EXACT_DUPLICATE")
    ]


def test_near_duplicate_boundary_decisions() -> None:
    assert NEAR_DUPLICATE_JACCARD_THRESHOLD == 0.8
    # 10-word texts differing in one word: 8 shared of 10 bigrams = 0.8.
    near_a = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    near_b = "alpha beta gamma delta epsilon zeta eta theta iota lambda"
    kept, rejections = deduplicate_records(
        _validated(
            _record("synthetic-rec-001", content=near_a),
            _record("synthetic-rec-002", content=near_b),
        )
    )
    assert [record.record_id for record in kept] == ["synthetic-rec-001"]
    assert [entry.code for entry in rejections] == ["NEAR_DUPLICATE"]
    # 0.667 similarity stays distinct.
    kept, rejections = deduplicate_records(
        _validated(
            _record("synthetic-rec-001", content="the cat sat on the mat"),
            _record("synthetic-rec-002", content="the cat sat on the rug"),
        )
    )
    assert len(kept) == 2
    assert rejections == ()
    # Unrelated texts stay distinct.
    kept, rejections = deduplicate_records(
        _validated(
            _record("synthetic-rec-001", content="alpha beta gamma"),
            _record("synthetic-rec-002", content="delta epsilon zeta"),
        )
    )
    assert len(kept) == 2
    assert rejections == ()


def test_conflicting_labels_quarantined_whole() -> None:
    kept, rejections = deduplicate_records(
        _validated(
            _record("synthetic-rec-001", content="same content here", label="supports"),
            _record("synthetic-rec-002", content="same content here", label="refutes"),
        )
    )
    assert kept == ()
    assert sorted(entry.code for entry in rejections) == [
        "LABEL_CONFLICT",
        "LABEL_CONFLICT",
    ]


def test_different_provenance_same_content_deduplicated() -> None:
    kept, rejections = deduplicate_records(
        _validated(
            _record(
                "synthetic-rec-002",
                content="same content here",
                provenance="synthetic:doc-2",
            ),
            _record(
                "synthetic-rec-001",
                content="same content here",
                provenance="synthetic:doc-1",
            ),
        )
    )
    assert [record.record_id for record in kept] == ["synthetic-rec-001"]
    assert [entry.code for entry in rejections] == ["EXACT_DUPLICATE"]


def test_dedup_counts_stable_under_reordering() -> None:
    records = _validated(
        _record("synthetic-rec-001", content="alpha beta gamma"),
        _record("synthetic-rec-002", content="alpha beta gamma"),
        _record("synthetic-rec-003", content="delta epsilon zeta"),
    )
    first = deduplicate_records(records)
    second = deduplicate_records(tuple(reversed(records)))
    assert [record.record_id for record in first[0]] == [
        record.record_id for record in second[0]
    ]
    assert first[1] == second[1]


# --- splitting ---


def _grouped_fixture():
    return [
        _record(
            f"synthetic-rec-00{i}", content=f"synthetic content number {i}", group=group
        )
        for i, group in enumerate(
            [
                "synthetic-group-001",
                "synthetic-group-001",
                "synthetic-group-002",
                "synthetic-group-003",
                "synthetic-group-004",
                "synthetic-group-005",
            ],
            start=1,
        )
    ]


def test_same_seed_same_input_byte_identical() -> None:
    first = _prep(_grouped_fixture())
    second = _prep(_grouped_fixture())
    assert first == second
    assert (
        first.split_manifest.model_dump_json()
        == second.split_manifest.model_dump_json()
    )


def test_different_seeds_both_valid() -> None:
    records = _grouped_fixture()
    first = _prep(
        records,
        split_config=SplitConfig(
            seed=7, train_ratio=0.6, validation_ratio=0.2, test_ratio=0.2
        ),
    )
    second = _prep(
        records,
        split_config=SplitConfig(
            seed=8, train_ratio=0.6, validation_ratio=0.2, test_ratio=0.2
        ),
    )
    for result in (first, second):
        verify_split(
            result.split_manifest,
            [record for part in result.partitions for record in part.records],
        )
    assert first == _prep(
        records,
        split_config=SplitConfig(
            seed=7, train_ratio=0.6, validation_ratio=0.2, test_ratio=0.2
        ),
    )


def test_related_records_never_cross_partitions() -> None:
    result = _prep(_grouped_fixture())
    seen: dict[str, str] = {}
    for part in result.partitions:
        for record in part.records:
            if record.group_id in seen:
                assert seen[record.group_id] == part.partition
            seen[record.group_id] = part.partition
    groups_in_train = {record.group_id for record in partition_records(result, "train")}
    for other in ("validation", "test"):
        assert groups_in_train.isdisjoint(
            {record.group_id for record in partition_records(result, other)}
        )


def test_exact_duplicates_never_cross_partitions() -> None:
    result = _prep(
        [
            _record(
                "synthetic-rec-001",
                content="same content here",
                group="synthetic-group-001",
            ),
            _record(
                "synthetic-rec-002",
                content="same content here",
                group="synthetic-group-002",
            ),
            _record(
                "synthetic-rec-003",
                content="other content here",
                group="synthetic-group-003",
            ),
            _record(
                "synthetic-rec-004",
                content="fourth content here",
                group="synthetic-group-004",
            ),
            _record(
                "synthetic-rec-005",
                content="fifth content here",
                group="synthetic-group-005",
            ),
            _record(
                "synthetic-rec-006",
                content="sixth content here",
                group="synthetic-group-006",
            ),
        ]
    )
    kept = [record.record_id for part in result.partitions for record in part.records]
    assert kept.count("synthetic-rec-001") + kept.count("synthetic-rec-002") == 1


def test_no_reappearance_of_excluded_records() -> None:
    result = _prep(
        [
            _record("synthetic-rec-001", group="synthetic-group-001"),
            _record(
                "synthetic-rec-002",
                content="second content",
                group="synthetic-group-002",
            ),
            _record(
                "synthetic-rec-001",
                content="other content",
                group="synthetic-group-003",
            ),
            _record("synthetic-rec-003", content="", group="synthetic-group-004"),
            _record(
                "synthetic-rec-004",
                content="fourth content",
                group="synthetic-group-005",
            ),
            _record(
                "synthetic-rec-005",
                content="fifth content",
                group="synthetic-group-006",
            ),
        ]
    )
    kept = [record.record_id for part in result.partitions for record in part.records]
    assert kept.count("synthetic-rec-001") == 1
    assert "synthetic-rec-003" not in kept
    assert "DUPLICATE_RECORD_ID" in [entry.code for entry in result.rejections]
    assert "EMPTY_CONTENT" in [entry.code for entry in result.rejections]


def test_impossible_split_fails_explicitly() -> None:
    with pytest.raises(DatasetPreparationError) as exc:
        _prep([_record("synthetic-rec-001", group="synthetic-group-001")])
    assert exc.value.code == "INSUFFICIENT_GROUPS"


def test_integrity_validator_rejects_tampering() -> None:
    result = _prep(_grouped_fixture())
    records = [record for part in result.partitions for record in part.records]
    tampered_counts = result.split_manifest.model_copy(
        update={"train_count": result.split_manifest.train_count + 1}
    )
    with pytest.raises(DatasetPreparationError) as exc:
        verify_split(tampered_counts, records)
    assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"
    tampered_hash = result.split_manifest.model_copy(
        update={"assignment_hash": "0" * 64}
    )
    with pytest.raises(DatasetPreparationError) as exc:
        verify_split(tampered_hash, records)
    assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"
    tampered_dataset_hash = result.split_manifest.model_copy(
        update={"dataset_integrity_hash": "0" * 64}
    )
    with pytest.raises(DatasetPreparationError) as exc:
        verify_split(tampered_dataset_hash, records)
    assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"
    swapped = list(result.split_manifest.assignments)
    first = swapped[0]
    other_partition = "validation" if first.partition == "train" else "train"
    swapped[0] = first.model_copy(update={"partition": other_partition})
    tampered_assign = result.split_manifest.model_copy(
        update={"assignments": tuple(swapped)}
    )
    with pytest.raises(DatasetPreparationError) as exc:
        verify_split(tampered_assign, records)
    assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"
    dropped = [record for record in records if record.group_id != "synthetic-group-001"]
    with pytest.raises(DatasetPreparationError) as exc:
        verify_split(result.split_manifest, dropped)
    assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"


def test_test_partition_isolated_by_accessor() -> None:
    result = _prep(_grouped_fixture())
    train_ids = {record.record_id for record in partition_records(result, "train")}
    for other in ("validation", "test"):
        assert train_ids.isdisjoint(
            {record.record_id for record in partition_records(result, other)}
        )
    total = sum(
        len(partition_records(result, name)) for name in ("train", "validation", "test")
    )
    assert total == result.dataset_manifest.record_count


# --- offline behavior ---


def test_no_network_model_or_hosted_dependency() -> None:
    package = (
        pathlib.Path(__file__).parent.parent / "src" / "rop" / "dataset_preparation"
    )
    imported: set[str] = set()
    files = ["__init__.py", "pipeline.py"]
    for name in files:
        for line in (package / name).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("import "):
                imported.add(stripped.split()[1].split(".")[0])
            elif stripped.startswith("from "):
                imported.add(stripped.split()[1].split(".")[0])
    forbidden = {
        "anthropic",
        "gemini",
        "httpx",
        "ollama",
        "openai",
        "os",
        "requests",
        "sklearn",
        "socket",
        "subprocess",
        "torch",
        "transformers",
        "urllib",
    }
    assert not (imported & forbidden)


def test_manifest_carries_no_raw_content() -> None:
    result = _prep(_grouped_fixture())
    dumped = json.dumps(result.dataset_manifest.model_dump(mode="json"), sort_keys=True)
    assert "synthetic content number" not in dumped
    assert result.dataset_manifest.record_count == len(
        [record for part in result.partitions for record in part.records]
    )


def test_content_hash_chain_binds_dataset() -> None:
    first = _prep(_grouped_fixture())
    altered = []
    for record in _grouped_fixture():
        if record["record_id"] == "synthetic-rec-001":
            record = dict(record, content_text="altered content here")
        altered.append(record)
    second = _prep(altered)
    assert (
        first.dataset_manifest.record_integrity_hash
        != second.dataset_manifest.record_integrity_hash
    )


def _modified_raw(field, value):
    out = []
    for record in _grouped_fixture():
        if record["record_id"] == "synthetic-rec-001":
            record = dict(record)
            record[field] = value
        out.append(record)
    return out


def _modified_validated(field, value, extra_auth=()):
    raws = _modified_raw(field, value)
    registry = _registry(*([_auth()] + list(extra_auth)))
    return tuple(
        validate_record(
            raw,
            allowed_labels=tuple(LABELS),
            authorizations=registry,
            purpose=PURPOSE,
            operation="training",
            as_of=AS_OF,
        )
        for raw in raws
    )


def _integrity_of(records) -> str:
    return dataset_integrity_hash(records)


def test_label_change_alters_integrity_hash() -> None:
    first = _prep(_grouped_fixture())
    modified = _modified_validated("label", "refutes")
    assert first.dataset_manifest.record_integrity_hash != _integrity_of(modified)
    with pytest.raises(DatasetPreparationError) as exc:
        verify_split(first.split_manifest, modified)
    assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"


def test_group_change_alters_integrity_hash() -> None:
    first = _prep(_grouped_fixture())
    modified = _modified_validated("group_id", "synthetic-group-009")
    assert first.dataset_manifest.record_integrity_hash != _integrity_of(modified)
    with pytest.raises(DatasetPreparationError) as exc:
        verify_split(first.split_manifest, modified)
    assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"


def test_source_change_alters_integrity_hash() -> None:
    first = _prep(_grouped_fixture())
    extra = _auth(source_id="synthetic-test-source-002")
    modified = _modified_validated("source_id", "synthetic-test-source-002", [extra])
    assert first.dataset_manifest.record_integrity_hash != _integrity_of(modified)


def test_provenance_change_alters_integrity_hash() -> None:
    first = _prep(_grouped_fixture())
    modified = _modified_validated("provenance_ref", "synthetic:doc-9")
    assert first.dataset_manifest.record_integrity_hash != _integrity_of(modified)


def test_record_id_change_alters_integrity_hash() -> None:
    first = _prep(_grouped_fixture())
    modified = _modified_validated("record_id", "synthetic-rec-009")
    assert first.dataset_manifest.record_integrity_hash != _integrity_of(modified)


def test_same_records_different_order_identical_hash() -> None:
    first = _prep(_grouped_fixture())
    shuffled = list(reversed(_grouped_fixture()))
    second = _prep(shuffled)
    assert first == second
    assert (
        first.dataset_manifest.record_integrity_hash
        == second.dataset_manifest.record_integrity_hash
    )


def test_legacy_content_only_hash_does_not_verify() -> None:
    import hashlib

    from rop.dataset_preparation.pipeline import canonical_json_bytes

    result = _prep(_grouped_fixture())
    records = [record for part in result.partitions for record in part.records]
    legacy = hashlib.sha256(
        canonical_json_bytes(sorted(record.content_hash for record in records))
    ).hexdigest()
    assert legacy != result.dataset_manifest.record_integrity_hash
    tampered = result.split_manifest.model_copy(
        update={"dataset_integrity_hash": legacy}
    )
    with pytest.raises(DatasetPreparationError) as exc:
        verify_split(tampered, records)
    assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"


def test_empty_nonzero_partition_fails_explicitly() -> None:
    # Seed 2 with (0.6, 0.2, 0.2) assigns all six fixture groups to
    # train/test, leaving validation empty under the hash algorithm.
    records = [
        _record(
            f"synthetic-rec-00{i}", content=f"synthetic content number {i}", group=group
        )
        for i, group in enumerate(
            [f"synthetic-group-00{j}" for j in range(1, 7)], start=1
        )
    ]
    with pytest.raises(DatasetPreparationError) as exc:
        _prep(
            records,
            split_config=SplitConfig(
                seed=2, train_ratio=0.6, validation_ratio=0.2, test_ratio=0.2
            ),
        )
    assert exc.value.code == "EMPTY_PARTITION"


def test_zero_ratio_partition_legitimately_empty() -> None:
    result = _prep(
        _grouped_fixture(),
        split_config=SplitConfig(
            seed=7, train_ratio=1.0, validation_ratio=0.0, test_ratio=0.0
        ),
    )
    assert partition_records(result, "validation") == ()
    assert partition_records(result, "test") == ()
    assert (
        len(partition_records(result, "train")) == result.dataset_manifest.record_count
    )
    verify_split(
        result.split_manifest,
        [record for part in result.partitions for record in part.records],
    )


def test_empty_partition_tampering_detected() -> None:
    result = _prep(_grouped_fixture())
    records = [record for part in result.partitions for record in part.records]
    reduced = result.split_manifest.model_copy(
        update={
            "assignments": tuple(
                entry
                for entry in result.split_manifest.assignments
                if entry.partition == "train"
            )
        }
    )
    with pytest.raises(DatasetPreparationError) as exc:
        verify_split(reduced, records)
    assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"
