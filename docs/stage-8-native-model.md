# Stage 8 Native Model (Task 209)

Project-owned, randomly initialized compact encoder-style Transformer
for a narrow synthetic classification task. No pretrained weights,
tokenizer, vocabulary, checkpoint, embedding, downloaded artifact,
training loop, inference service, network access, or GPU requirement
exists in this path.

## Task and rationale

The initial native model targets a **synthetic multi-class
classification task** with a small, fixed label set (e.g., 4 classes).
This task was chosen because:

- It is the simplest non-trivial supervised task that exercises the
  full encoder stack (embeddings, attention, feed-forward, classifier).
- It admits a clear, predeclared evaluation metric (accuracy) against
  the deterministic baseline from Task 206.
- It does not require free-form generation, sequence labeling, or
  open-ended output validation.
- The synthetic dataset pipeline (Task 207) and tokenizer/vocabulary
  (Task 208) already provide the necessary data preparation path.

**An untrained, randomly initialized model has no demonstrated task
competence.** Its outputs are meaningless noise and must never be
represented as evidence, findings, confidence in a real-world claim,
or a validated prediction.

## Architecture

**Identifier:** `tiny-encoder-v1`  
**Version:** `1.0`

```
Input token IDs (batch, seq_len) → Embeddings → Encoder × L → Classifier → Logits (batch, num_classes)
```

### Components

1. **Token embeddings**: `nn.Embedding(vocab_size, hidden_dim)`
2. **Positional embeddings**: `nn.Embedding(max_seq_len, hidden_dim)`
3. **Encoder blocks** (× `num_layers`):
   - Multi-head self-attention (`nn.MultiheadAttention`, `batch_first=True`)
   - Residual + LayerNorm
   - Position-wise feed-forward (hidden → 4×hidden → hidden, GELU)
   - Residual + LayerNorm
   - Dropout throughout
4. **Classifier**: `nn.Linear(hidden_dim, num_classes)` on first token (CLS-style pooling)

### Configuration limits

| Parameter | Min | Max | Description |
|-----------|-----|-----|-------------|
| `vocab_size` | 2 | 8192 | Vocabulary size (incl. reserved) |
| `hidden_dim` | 16 | 256 | Model dimension |
| `num_layers` | 1 | 4 | Encoder depth |
| `num_heads` | 1 | 8 | Attention heads (must divide `hidden_dim`) |
| `max_seq_len` | 1 | 512 | Maximum sequence length |
| `num_classes` | 2 | 128 | Output classes |
| `dropout` | 0.0 | 0.5 | Dropout probability |
| `init_seed` | 0 | 2³²-1 | Initialization RNG seed |
| `init_std` | >0 | 1.0 | Initialization std deviation |

**Conservative bounds:** Total trainable parameters ≤ 500,000.

### Parameter count formula

```
token_emb      = vocab_size × hidden_dim
pos_emb        = max_seq_len × hidden_dim
per_layer      = attn_params + ln_params + ff_params
  attn_params  = 3×hidden² + 3×hidden + hidden² + hidden  (in_proj + out_proj)
  ln_params    = 4×hidden  (two LayerNorms)
  ff_params    = 8×hidden² + 8×hidden  (two Linear + biases)
classifier     = hidden_dim × num_classes + num_classes
total          = token_emb + pos_emb + num_layers × per_layer + classifier
```

The exact count is verified at initialization and recorded in metadata.

## Initialization procedure

1. **Validate** configuration (dimensions, divisibility, bounds).
2. **Estimate** parameter count; reject if > 500,000 before allocation.
3. **Allocate** model with `NativeModel(config)`.
4. **Create** a dedicated `torch.Generator()` seeded with `config.init_seed`.
5. **Initialize** all weight tensors with `normal_(mean=0.0, std=config.init_std)` using the dedicated generator.
6. **Zero** all bias tensors.
7. **Set** LayerNorm weights to 1, biases to 0.
8. **Verify** all parameters are finite (no NaN/Inf).
9. **Set** model to `eval()` mode.
10. **Return** initialized `NativeModel`.

### Reproducibility

- **Identical config + identical seed → identical parameter values** (bitwise).
- **Different seed → different parameters** (tested deterministically).
- Initialization uses a **local generator**, never the global RNG state.
- Parameter values are hashed (SHA-256 over sorted-name concatenated bytes) to produce `init_hash`.
- Configuration is hashed (SHA-256 over canonical JSON) to produce `config_hash`.
- Both hashes are recorded in `NativeModelMetadata`.

**Reproducible initialization does not establish predictive ability,
safety, or correctness.** It only guarantees that the same configuration
and seed yield the same initial weights.

## Parameter inspection

- `count_parameters(model)` → total trainable parameter count.
- `build_model_spec(model, config)` → `NativeModelSpec` containing:
  - `NativeModelMetadata` (version, architecture, hashes, counts, seed, scope)
  - `parameter_shapes: dict[str, list[int]]` (name → shape list)
- `verify_model(model, config=None)` → recomputes parameter count and
  `init_hash`; validates against recorded values; optionally verifies
  `config_hash`. Raises `NativeModelError` on mismatch.

All parameter tensors are `torch.float32`.

## Construction and usage

```python
from rop.schemas.native_model import NativeModelConfig
from rop.native_model.native_model import initialize_model, verify_model

config = NativeModelConfig(
    model_version="1.0",
    architecture="tiny-encoder-v1",
    vocab_size=1000,
    hidden_dim=128,
    num_layers=3,
    num_heads=4,
    max_seq_len=128,
    num_classes=4,
    dropout=0.1,
    init_seed=12345,
    init_std=0.02,
)

model = initialize_model(config)
verify_model(model)  # passes

# Forward pass (untrained - outputs are random)
import torch
token_ids = torch.randint(0, config.vocab_size, (2, 32))
logits = model(token_ids)  # shape (2, 4)
```

## Prohibitions and scope

- **No pretrained weights** — all parameters randomly initialized.
- **No pretrained tokenizer/vocabulary** — uses Task 208 project-controlled vocabulary.
- **No network access** — no downloads, hub access, or remote calls.
- **No training loop** — Task 210.
- **No checkpoint/save/load** — Task 211.
- **No inference service** — Task 212.
- **No advisory adapter** — Task 213.
- **No offline isolation framework** — Task 214.
- **No acceptance gate** — Task 215.
- **No real/unauthorized data** — `data_scope: synthetic-test-only` enforced.

## Limitations

- Randomly initialized model has **no task competence**.
- CLS-style pooling on first token assumes sequences have a meaningful
  first position; for synthetic data this is a design choice.
- No subword merging, no case folding, no semantic understanding.
- CPU-only in this task; GPU path optional in later tasks.
- Maximum 500K parameters limits expressivity intentionally.

## Next task boundary

Task 210 will implement the reproducible training and validation loop,
including optimizer, scheduler, checkpointing, and held-out evaluation
against predeclared thresholds.