#pragma once

#include <cmath>
#include <cstddef>

namespace cuda_kernels {

namespace detail {

inline bool is_valid_layernorm_epsilon(float epsilon) noexcept {
  return std::isfinite(epsilon) && epsilon > 0.0f;
}

}  // namespace detail

// Row-wise FP32 layer normalization for contiguous row-major input [rows, features].
// gamma and beta each contain features floats. The output range must not overlap
// input, gamma, or beta. gamma and beta may overlap each other because both are
// read-only. All pointers must reference device allocations large enough for
// their documented shapes when both dimensions are non-zero.
// Epsilon must be finite and positive; the default is 1e-5f. Invalid epsilon
// aborts using the library's fail-fast CUDA error policy. Variance is the
// population variance (division by features). Zero dimensions are a no-op.
//
// Launches asynchronously on stream (cudaStream_t represented as void*).
// Synchronize that stream before consuming output.
void launch_layernorm_fp32(const float* input, const float* gamma, const float* beta,
                           float* output, std::size_t rows, std::size_t features,
                           float epsilon = 1.0e-5f, void* stream = nullptr);

}  // namespace cuda_kernels
