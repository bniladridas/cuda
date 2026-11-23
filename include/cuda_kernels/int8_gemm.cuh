#pragma once

#include <cstddef>
#include <cstdint>

namespace cuda_kernels {

// Row-major signed-int8 GEMM: C[M,N] = A[M,K] * B[K,N].
// Products are accumulated exactly into signed int32. For symmetric
// per-tensor quantization with zero-points fixed at zero, dequantize each
// output as float(C[row,col]) * (scale_a * scale_b).
// K must be <= 131071 so the worst-case absolute sum (K * 128 * 128)
// remains representable in int32. Zero dimensions are no-ops.
// Inputs and output must not overlap. The launch is asynchronous on stream.
void launch_gemm_int8(const std::int8_t* a, const std::int8_t* b, std::int32_t* c,
                      std::size_t m, std::size_t n, std::size_t k, void* stream);

}  // namespace cuda_kernels
