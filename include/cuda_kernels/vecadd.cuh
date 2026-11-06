#pragma once

#include <cstddef>

namespace cuda_kernels {

// c[i] = a[i] + b[i] for i in [0, n).
// Requires a, b, c to be device pointers with at least n floats allocated.
// Streams the launch on `stream` (cudaStream_t as void* to keep this header
// free of CUDA types).
void launch_vecadd(const float* a, const float* b, float* c, std::size_t n,
                   void* stream);

}  // namespace cuda_kernels
