#pragma once

#include <cstddef>

namespace cuda_kernels {

// c[i] = a[i] + b[i] for i in [0, n).
// Requires a, b, and c to be device pointers with at least n floats allocated.
// For n > 0, the three n-element ranges must be pairwise non-overlapping.
// In-place operation and partial overlap are unsupported. This matches the
// kernel's __restrict__ qualifiers. For n == 0, no pointers are accessed.
//
// Streams the launch on `stream` (cudaStream_t as void* to keep this header
// free of CUDA types). The function enqueues work and returns without
// synchronizing the stream. The caller must synchronize the relevant stream
// before reading c or otherwise depending on the result.
//
// An immediate CUDA API or kernel-launch error is checked with
// cudaGetLastError() and currently prints a diagnostic and aborts the process.
// A successful return does not mean device execution has completed. Errors
// raised during asynchronous execution may be reported by a later stream
// synchronization or another CUDA runtime operation.
void launch_vecadd(const float* a, const float* b, float* c, std::size_t n, void* stream);

}  // namespace cuda_kernels
