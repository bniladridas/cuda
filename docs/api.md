# CUDA launch and error-reporting contract

The public launchers `launch_vecadd`, `launch_reduce`, `launch_softmax`,
`launch_gemm_fp32`, `launch_layernorm_fp32`, and
`launch_attention_fp32, and
`launch_gemm_int8`` enqueue their kernels on the caller-supplied CUDA
stream. They do not synchronize that stream before returning.

## Caller responsibilities

- Pass a valid CUDA stream, or `nullptr` for the default stream.
- Keep device input, output, and scratch allocations alive until the queued
  work that uses them has completed.
- Synchronize the relevant stream before reading results on the host or
  consuming them from work that is not correctly ordered after the kernel.
- Check the result of the synchronization operation. A successful launcher
  return alone does not establish that asynchronous device execution succeeded.

## Error behavior

The implementation checks immediate CUDA API and kernel-launch status with
`cudaGetLastError()`. The current `CUDA_CHECK` implementation writes a
diagnostic to standard error and calls `std::abort()` when such a check fails.
This is intentionally fail-fast behavior, not an error code returned by the
public launcher.

Device execution errors that occur after enqueueing may only become visible
when the caller synchronizes the stream or performs another CUDA runtime
operation. Callers should therefore check synchronization results and must
not interpret a normal launcher return as proof that the kernel completed.

## Example: launch, synchronize, consume

This example shows the ordering contract for vector addition. Allocation and
copy operations are checked separately; the public launcher performs its own
immediate launch check.

```cpp
#include <cuda_runtime.h>

#include <cstdio>
#include <cstdlib>
#include <vector>

#include "cuda_kernels/vecadd.cuh"

static void check_cuda(cudaError_t status) {
  if (status != cudaSuccess) {
    std::fprintf(stderr, "CUDA error: %s\\n", cudaGetErrorString(status));
    std::abort();
  }
}

int main() {
  constexpr std::size_t n = 1024;
  constexpr std::size_t bytes = n * sizeof(float);
  std::vector<float> host_a(n, 1.0F);
  std::vector<float> host_b(n, 2.0F);
  std::vector<float> host_c(n);
  float *a = nullptr, *b = nullptr, *c = nullptr;
  cudaStream_t stream = nullptr;

  check_cuda(cudaStreamCreate(&stream));
  check_cuda(cudaMalloc(&a, bytes));
  check_cuda(cudaMalloc(&b, bytes));
  check_cuda(cudaMalloc(&c, bytes));

  check_cuda(cudaMemcpyAsync(a, host_a.data(), bytes,
                             cudaMemcpyHostToDevice, stream));
  check_cuda(cudaMemcpyAsync(b, host_b.data(), bytes,
                             cudaMemcpyHostToDevice, stream));
  cuda_kernels::launch_vecadd(a, b, c, n, stream);
  check_cuda(cudaMemcpyAsync(host_c.data(), c, bytes,
                             cudaMemcpyDeviceToHost, stream));

  // Wait for the queued copies and kernel. Async execution errors can surface
  // here, so check the synchronization result.
  check_cuda(cudaStreamSynchronize(stream));

  std::printf("c[0] = %.1f\\n", host_c[0]);

  check_cuda(cudaFree(a));
  check_cuda(cudaFree(b));
  check_cuda(cudaFree(c));
  check_cuda(cudaStreamDestroy(stream));
  return 0;
}
```

The example initializes its inputs and prints one result after synchronization.
A complete application should verify the full output and check every CUDA
operation, including copies and synchronization.

## Row-wise softmax

`launch_softmax(input, output, rows, columns, stream)` accepts contiguous
row-major FP32 input and output matrices. Each row is normalized independently
using max-subtracted exponentials. The implementation uses one 256-thread CUDA
block per row. Positive, non-power-of-two column counts are supported. If
either dimension is zero, the call is a no-op and does not access either
pointer. Input and output ranges must not overlap. One block is launched per
row, so `rows` must fit the device grid-x limit. The launch is asynchronous
and follows the same stream and error-reporting contract described above.

## Row-wise layer normalization

`launch_layernorm_fp32(input, gamma, beta, output, rows, features, epsilon, stream)`
accepts contiguous row-major FP32 input with shape `[rows, features]`, plus
per-feature `gamma` and `beta` arrays of length `features`. Each row uses
population variance and computes
`(x - mean) / sqrt(variance + epsilon) * gamma + beta`. Epsilon defaults to
`1e-5f` and must be finite and strictly positive when both dimensions are
non-zero. An invalid epsilon triggers the library's fail-fast
`cudaErrorInvalidValue` check. A zero row or feature dimension is a no-op and
does not access any pointer or validate epsilon.

The output range must not overlap the input, gamma, or beta ranges. The three
read-only input ranges may overlap. The caller is responsible for providing
valid device pointers and sufficient storage for the documented shapes.
One CUDA block is launched per row. The operation is asynchronous and follows
the stream and synchronization contract above.

## Single-head scaled dot-product attention

`launch_attention_fp32(q, k, v, output, scores, probabilities, lq, lk, d, dv, stream)`
computes non-causal single-head FP32 attention for contiguous row-major
`Q[Lq,D]`, `K[Lk,D]`, and `V[Lk,Dv]`:
`softmax(Q * K^T / sqrt(D)) * V`. Query and key lengths may differ.
If any dimension is zero, the call is a no-op. The query length must not exceed
65,535 because it maps to the score and value kernels' grid-y dimension.
The launcher rejects dimensions whose element-count products would overflow
`size_t`, or whose score/value grids exceed the CUDA grid-x limit.

The caller provides two separate scratch buffers, each containing at least
`Lq*Lk` floats. The launcher materializes scaled scores, applies the existing
stable row-wise softmax, then computes the weighted value sum. The output and
scratch ranges must not overlap each other or Q, K, or V. The caller must keep
all allocations alive until the stream completes. This staged baseline is not
a fused or memory-efficient attention implementation. GPU runtime validation
remains pending NVIDIA hardware.


## Symmetric int8 matrix multiplication

`launch_gemm_int8(a, b, c, m, n, k, stream)` computes row-major signed
int8 matrix multiplication with exact signed int32 accumulation. Inputs use
symmetric per-tensor quantization with zero-points fixed at zero. The output is
the raw int32 accumulator, not a floating-point tensor. If the input scales
are (s_a) and (s_b), the corresponding real-valued output is
`float(c[row,n]) * (s_a * s_b)`; callers own scale storage and dequantization.

The implementation uses a portable scalar CUDA arithmetic path and does not
depend on architecture-specific integer matrix instructions. Each output is
computed independently. For all possible int8 input values, the absolute sum
is bounded by `K * 128 * 128`, so the launcher requires
`K <= 131071` to prevent signed int32 overflow. Zero dimensions are no-ops.
The input and output ranges must not overlap. The launch is asynchronous and
uses the caller's stream. GPU execution and performance measurements remain
pending NVIDIA hardware.
