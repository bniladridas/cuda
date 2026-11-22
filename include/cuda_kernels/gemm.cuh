#pragma once

#include <cstddef>

namespace cuda_kernels {

// Row-major FP32 matrix multiplication: C[M,N] = A[M,K] * B[K,N].
// A, B, and C are device pointers. The output range must not overlap either
// input range. Dimensions must be positive. The launch is ordered on stream;
// cudaStream_t is represented as void* to keep this header CUDA-independent.
void launch_gemm_fp32(const float* a, const float* b, float* c, std::size_t m,
                      std::size_t n, std::size_t k, void* stream);

}  // namespace cuda_kernels
