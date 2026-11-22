#include "cuda_kernels/int8_gemm.cuh"

#include <cstddef>
#include <cstdint>
#include <limits>

#include <cuda_runtime.h>

#include "cuda_check.h"

namespace cuda_kernels {
namespace {

constexpr unsigned int kBlockSize = 256;
constexpr std::size_t kMaxGridX = 2147483647ULL;
constexpr std::size_t kMaxSafeK =
    static_cast<std::size_t>(std::numeric_limits<std::int32_t>::max()) / (128U * 128U);

__global__ void gemm_int8_kernel(const std::int8_t* __restrict__ a,
                                 const std::int8_t* __restrict__ b,
                                 std::int32_t* __restrict__ c, std::size_t m,
                                 std::size_t n, std::size_t k) {
  const std::size_t index =
      static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
  const std::size_t total = m * n;
  if (index >= total) return;

  const std::size_t row = index / n;
  const std::size_t col = index % n;
  std::int32_t accumulator = 0;
  for (std::size_t inner = 0; inner < k; ++inner) {
    const std::int32_t lhs = static_cast<std::int32_t>(a[row * k + inner]);
    const std::int32_t rhs = static_cast<std::int32_t>(b[inner * n + col]);
    accumulator += lhs * rhs;
  }
  c[index] = accumulator;
}

}  // namespace

void launch_gemm_int8(const std::int8_t* a, const std::int8_t* b, std::int32_t* c,
                      std::size_t m, std::size_t n, std::size_t k, void* stream) {
  if (m == 0 || n == 0 || k == 0) return;

  constexpr std::size_t kSizeMax = std::numeric_limits<std::size_t>::max();
  const bool products_fit = m <= kSizeMax / k && k <= kSizeMax / n &&
                            m <= kSizeMax / n;
  const std::size_t total = products_fit ? m * n : 0;
  const std::size_t blocks =
      total / kBlockSize + static_cast<std::size_t>(total % kBlockSize != 0);
  CUDA_CHECK(products_fit && k <= kMaxSafeK && blocks <= kMaxGridX
                 ? cudaSuccess
                 : cudaErrorInvalidValue);

  gemm_int8_kernel<<<static_cast<unsigned int>(blocks), kBlockSize, 0,
                     reinterpret_cast<cudaStream_t>(stream)>>>(a, b, c, m, n, k);
  CUDA_CHECK_LAST_ERROR();
}

}  // namespace cuda_kernels
