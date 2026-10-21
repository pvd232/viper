# Weight updates inside worker autocast

VIPER's worker autocast context could keep reduced precision copies of weights
alive across optimizer updates. Affected training could continue using the
previous weights. The failure was observed in the JEP C-STS study on 21 October
2026 with PyTorch 2.14.0 and an NVIDIA L4.

## Reproduction

Initialize a linear layer with the identity matrix and use a vector of ones as
input. Enter a disabled outer autocast context, run a BF16 forward in a nested
context, double the weights, and run another BF16 forward. The original context
returns ones twice. The corrected context returns ones followed by twos.

The [regression tests](../../tests/test_autocast_weight_updates.py) exercise this
update and repeated backward passes on CPU and CUDA. The CPU reproduction
returned `[1, 1, 1, 1]` after the update before the fix and `[2, 2, 2, 2]` with
the fix. The pull request records CUDA validation.

## Cause and repair

PyTorch increments autocast nesting when entering a context, including a
disabled context. It clears the weight cache when the outermost context exits.
VIPER wrapped the entire user function in that context. An inner user context
could therefore reuse cached casts after the optimizer changed the original
weights. See PyTorch's
[autocast implementation](https://github.com/pytorch/pytorch/blob/v2.14.0/torch/amp/autocast_mode.py)
and [AMP guidance](https://docs.pytorch.org/docs/2.14/amp.html).

The [shared runtime helper](../../src/viper/runtime.py) now returns a null
context when framework autocast is disabled. User contexts then clear their
caches when each forward context exits. When framework autocast is enabled,
the helper disables its weight cache. Nested user contexts inherit that cache
setting by default. An explicit user override of the cache remains controlled
by that user context.

Both the [stage worker](../../src/viper/_workers/stages.py) and the
[metric worker](../../src/viper/_workers/metrics.py) use this helper. The metric
worker now passes its declared backend explicitly. A CPU metric therefore uses
CPU autocast on a host that also has a CUDA device.

The null context preserves the caller's ambient autocast state. VIPER's fresh
workers begin with autocast disabled, and their startup receipts continue to
check the requested precision. An enabled framework context restores the
caller's cache setting on exit.

## Scope and runtime effect

The fixed workflow is a training stage with a user forward autocast context,
backward computation, and an optimizer update repeated in a loop. Source,
settings, inputs, artifacts and receipt schemas retain their existing form.
The change applies by default and requires no new author action. Framework
autocast performs fresh casts after updates. Disabled framework autocast
creates no PyTorch context. The JEP fitting failure had already been corrected
locally by disabling the inner cache; this change repairs the library helper.

Training with no nested mixed precision and disabled framework autocast has no
reduced precision weight cache. The original JEP synthetic pilot followed that
path. Its results require their own scientific interpretation.

## Validation

The pull request records commands, CPU and CUDA results, and a focused runtime
comparison. Tests check changed weights, repeated backward passes, and cache
state restoration. Existing policy, metric provenance and execution tests check
worker receipts and saved run behavior.
