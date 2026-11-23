# Benchmark methodology

The rule this repository follows: **correctness gates performance**. The
benchmark binary checks every kernel against a CPU reference at every size
before it collects a single timing, and exits non-zero if any case is wrong.

## Harness

`benchmarks/bench.h`.

- **Timing unit**: `cudaEventRecord` around a batch of `--iterations` launches,
  then `cudaEventSynchronize`. Event-based timing measures device execution
  without host-side wall-clock noise, but the figure is still launch-to-
  completion for the batch, which is what a caller actually pays.
- **Warmup**: a discarded batch of `--warmup` launches runs first, so first-touch
  page faults, context setup and clock ramp-up do not land in samples.
- **Replication**: `--reps` independent timed batches. Each batch's total is
  divided by its iteration count to give a per-launch time, and those per-batch
  times are summarised.
- **Reported statistic**: the **median** of per-batch times. The mean is
  sensitive to a single scheduler hiccup; the min is the best case and is
  reported too but is not the headline figure. p90 is included to show spread.
- **p90 convention**: nearest rank. For sorted samples and percentile fraction
  `p`, select the value at one-based rank `ceil(p * sample_count)`, with `p` in
  `[0, 1]`. The empty sample set returns `0`; `p = 0` selects the minimum and
  `p = 1` selects the maximum. With the default seven batches, p90 is the
  maximum sample. This conservative convention avoids understating the tail
  with a small sample count.
- **Defaults**: 200 iterations, 7 batches, 20 warmup launches.
- **Input limits**: each value must be a positive decimal integer. Iterations and warmup are capped at 100,000, batches at 1,000, and the product of iterations and batches at 100,000 timed launches. This rejects malformed input and bounds accidental long runs before CUDA work begins.

## Metrics

- Raw time in milliseconds per launch.
- **Achieved bandwidth** = bytes moved / time, in GB/s (decimal). Bytes moved:
  `vecadd` reads 2 arrays and writes 1, so `3 * n * sizeof(float)`; `reduce`
  reads 1 array, so `n * sizeof(float)`, excluding the small partials and the
  second pass.
- Report achieved bandwidth as a fraction of the device's theoretical peak
  (from the vendor spec sheet) to compare against the hardware limit rather
  than against other code on other GPUs. The harness prints GB/s; the peak
  comparison is left to the reader with the device name recorded in every
  result file.

## Reproducibility

A reduction result is **not bit-reproducible across launch configurations**.
Floating-point addition is not associative, so grouping the sum into different
per-block partials changes the rounding, and the grouping depends on the block
count and chunk size. The same input on a different GPU (different SM count,
different block cap) can therefore differ in the last bits.

Bit-exact reproducibility is only achievable within one fixed launch geometry on
one device. Cross-device or cross-size comparisons must use a tolerance. The
tests use `max(|ref|, n)` as the error scale, which does not collapse when the
true sum is small. For sums that need bit-exactness regardless of geometry, use
an order-preserving or compensated scheme, which this kernel deliberately does
not implement.

## Recorded context

Every new JSON result published by `runners/benchmark.sh` carries the GPU
name, CUDA device UUID, PCI bus ID when the device exposes one, compute
capability, driver version, CUDA runtime version, iteration/batch/warmup
counts, the full Git commit SHA, and an ISO 8601 UTC completion timestamp.
The UUID identifies the CUDA device; the PCI bus ID is additional placement
context and may be JSON `null` in virtualized environments. Both fields are
validated by `benchmarks/plot_results.py` before a result is plotted. The
commit and timestamp are embedded in the JSON, so copying or renaming the
file does not detach its provenance. If the benchmark runs outside a Git
checkout, `git_commit` is JSON `null`; the timestamp is still recorded.
Older result files without device identifiers or embedded provenance remain
readable and are identified as legacy in plots. A number without this context
is not a result.

## What would make a result invalid

- Comparing figures across different GPUs without normalising by peak bandwidth.
- Timing without a warmup batch, or with a batch too short to exceed event
  resolution (~0.5 ms).
- Reporting only the minimum.
- Any timing from a build whose correctness gate failed.
- A GPU with background load or thermal throttling; check clocks before a run
  if the numbers look low.

## GPU correctness coverage

The vector-add correctness suite includes a capped-grid case with
`65,535 * 256 + 1` elements (16,776,961 floats). With 256 threads per block,
the requested block count exceeds the launcher's 65,535-block cap by one
logical block, so the test exercises the grid-stride loop after the capped
launch. The case checks every output against the CPU reference. It is registered
with the GPU test suite and runs under `GPU_REQUIRED=1` on an NVIDIA runner.
The test is compiled in CUDA CI, but runtime execution remains pending an
available NVIDIA device.

## Sizes

`2^16`, `2^20`, `2^24` elements. The smallest fits in cache on most devices and
is dominated by launch overhead; the largest is memory-bound on every current
card and is the meaningful bandwidth figure; the middle one falls between.

## GEMM benchmark

The FP32 GEMM benchmark is separate from the vector-add and reduction
bandwidth harness. It runs a CPU-reference correctness gate for every shape
before timing, then records M, N, K, the 16×16 tile shape, median/min/p90
milliseconds, GPU name, compute capability, driver, CUDA runtime, full Git
commit, and UTC timestamp. Run it with:

```bash
bash runners/gemm-benchmark.sh
```

The recorded measurements are workload-specific. Do not compare them with
vector-add bandwidth figures or claim a speedup without a controlled baseline.


## LayerNorm benchmark

The FP32 row-wise LayerNorm benchmark checks each workload against the
double-precision CPU reference before timing. It covers a small launch-bound
shape, a representative hidden width, and a wider row. It records rows,
features, epsilon, median/min/p90 latency, GPU name, compute capability,
driver, CUDA runtime, full Git commit, and UTC timestamp.

Run it on an NVIDIA host after building:

```bash
bash runners/layernorm-benchmark.sh
```

Do not compare these measurements with GEMM or bandwidth-kernel figures.
They describe only this kernel, these shapes, and the recorded device.
