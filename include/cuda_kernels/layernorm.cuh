#pragma once

#include <cstddef>

namespace cuda_kernels {

// Row-wise FP32 layer normalization for contiguous row-major input [rows, features].
// gamma and beta each contain features floats. The output must not overlap input.
// Epsilon must be finite and positive; the default is 1e-5f. Variance is the
// population variance (division by features). Zero dimensions are a no-op.
//
// Launches asynchronously on stream (cudaStream_t represented as void*).
// Synchronize that stream before consuming output.
void launch_layernorm_fp32(const float* input, const float* gamma, const float* beta,
                           float* output, std::size_t rows, std::size_t features,
                           float epsilon = 1.0e-5f, void* stream = nullptr);

}  // namespace cuda_kernels
