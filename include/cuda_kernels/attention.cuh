#pragma once

#include <cstddef>

namespace cuda_kernels {

// Non-causal single-head scaled dot-product attention:
// output[Lq,Dv] = softmax(Q[Lq,D] * K[Lk,D]^T / sqrt(D)) * V[Lk,Dv].
// All matrices are contiguous row-major FP32 device allocations.
// scores and probabilities are separate Lq*Lk scratch allocations. The output
// must not overlap Q, K, V, scores, or probabilities; scratch must not overlap
// any input or output. Q, K, V, output, and scratch must remain alive until the
// supplied stream completes. Dimensions must be positive and Lq <= 65535.
// The staged implementation materializes scores and probabilities.
// Enqueues asynchronously on stream (cudaStream_t represented as void*).
void launch_attention_fp32(const float* q, const float* k, const float* v,
                           float* output, float* scores, float* probabilities,
                           std::size_t lq, std::size_t lk, std::size_t d,
                           std::size_t dv, void* stream);

}  // namespace cuda_kernels
