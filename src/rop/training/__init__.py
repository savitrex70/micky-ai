"""Task 210: bounded native training and validation loop package.

An explicitly invoked, resource-bounded training loop for the Task
209 model over Task 207 synthetic-test-only data and the Task 208
vocabulary. Importing this package never starts training; there is
no inference service, checkpointing, network, or GPU support here.
"""

from rop.training.loop import (
    EncodedExample,
    EncodedTrainingDataset,
    NativeTrainingError,
    build_training_dataset,
    run_training,
)

__all__ = [
    "EncodedExample",
    "EncodedTrainingDataset",
    "NativeTrainingError",
    "build_training_dataset",
    "run_training",
]
