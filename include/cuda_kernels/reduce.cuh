#pragma once

#include <cstddef>

namespace cuda_kernels {

// Sum of x[0..n). n == 0 yields 0.
//
// The reduction uses at most kReduceMaxBlocks partial sums, so callers can
// allocate scratch without querying the device. See launch_reduce_scratch_elems.

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
