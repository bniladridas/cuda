#pragma once

#include <cstddef>

namespace cuda_kernels {

// Sum of x[0..n). n == 0 yields 0.
//
// For n > 0, x must reference n readable elements, out must reference one
// writable element, and scratch must reference at least
// launch_reduce_scratch_elems<T>(n) writable elements. These three ranges must
// be pairwise non-overlapping. In-place reduction and partial overlap are
// unsupported. This matches the kernels' __restrict__ qualifiers.
//
// For n == 0, x and scratch are not accessed; out must still reference one
// writable element.
//
// The reduction uses at most kReduceMaxBlocks partial sums, so callers can
// allocate scratch without querying the device. See launch_reduce_scratch_elems.
//
// Not bit-reproducible across launch configurations. Floating-point addition is
// not associative, and the partial-sum grouping depends on the block count and
// chunk size, so changing either (e.g. a different GPU, a different n, or a
// change to kReduceMaxBlocks) can change the last bits of the result. Compare
// results within a documented tolerance, never for exact equality.
//
// Streams the launch on `stream` (cudaStream_t as void*). The function
// enqueues work and returns without synchronizing the stream. The caller must
// synchronize the relevant stream before reading out or otherwise depending
// on the result.
//
// An immediate CUDA API or kernel-launch error is checked with
// cudaGetLastError() and currently prints a diagnostic and aborts the process.
// A successful return does not mean device execution has completed. Errors
// raised during asynchronous execution may be reported by a later stream
// synchronization or another CUDA runtime operation.

// Upper bound on the number of per-block partial sums written in pass 1.
constexpr std::size_t kReduceMaxBlocks = 4096;

template <typename T>
constexpr std::size_t launch_reduce_scratch_elems(std::size_t n) {
  return n == 0 ? 0 : kReduceMaxBlocks;
}

void launch_reduce(const float* x, float* out, float* scratch, std::size_t n,
                   void* stream);
void launch_reduce(const double* x, double* out, double* scratch, std::size_t n,
                   void* stream);

}  // namespace cuda_kernels
