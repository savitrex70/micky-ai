"""Task 211: artifact manifest and checkpoint integrity package.

Narrow, secure manifest and checkpoint handling for the Task 209
``tiny-encoder-v1`` model and Task 210 training lineage. No pretrained
weights, external model files, downloads, inference, network, or
clinical logic live here.
"""

from rop.artifacts.checkpoints import (
    ArtifactError,
    apply_checkpoint_to_model,
    build_artifact_manifest,
    build_checkpoint_bytes,
    content_digest,
    load_artifact_files,
    parse_checkpoint_header,
    verify_artifact,
    verify_manifest_integrity,
    write_artifact_files,
)

__all__ = [
    "ArtifactError",
    "apply_checkpoint_to_model",
    "build_artifact_manifest",
    "build_checkpoint_bytes",
    "content_digest",
    "load_artifact_files",
    "parse_checkpoint_header",
    "verify_artifact",
    "verify_manifest_integrity",
    "write_artifact_files",
]
