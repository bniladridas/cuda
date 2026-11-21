# CUDA launch and error-reporting contract

The public launchers `launch_vecadd`, `launch_reduce`, and `launch_softmax` enqueue their kernels
on the caller-supplied CUDA stream. They do not synchronize that stream before
returning.

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
    std::fprintf(stderr, "CUDA error: %s\n", cudaGetErrorString(status));
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

  std::printf("c[0] = %.1f\n", host_c[0]);

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

`launch_softmax(input, output, rows, columns, stream)` accepts contiguous row-major FP32 input and output matrices. Each row is normalized independently using max-subtracted exponentials. Positive, non-power-of-two column counts are supported. If either dimension is zero, the call is a no-op and does not access either pointer. Input and output ranges must not overlap. One block is launched per row, so `rows` must fit the device grid-x limit. The launch is asynchronous and follows the same stream and error-reporting contract described above.\n