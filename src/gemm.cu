#include "cuda_kernels/gemm.cuh"

#include <cstddef>

#include <cuda_runtime.h>

#include "cuda_check.h"

namespace cuda_kernels {
namespace {

constexpr int kTile = 16;

__global__ void gemm_fp32_tiled_kernel(const float* __restrict__ a,
                                      const float* __restrict__ b,
                                      float* __restrict__ c, std::size_t m,
                                      std::size_t n, std::size_t k) {
  __shared__ float tile_a[kTile][kTile];
  __shared__ float tile_b[kTile][kTile];

  const int row = static_cast<int>(blockIdx.y) * kTile + threadIdx.y;
  const int col = static_cast<int>(blockIdx.x) * kTile + threadIdx.x;
  float acc = 0.0f;

  const std::size_t tiles = (k + kTile - 1) / kTile;
  for (std::size_t tile = 0; tile < tiles; ++tile) {
    const std::size_t a_col = tile * kTile + threadIdx.x;
    const std::size_t b_row = tile * kTile + threadIdx.y;

    tile_a[threadIdx.y][threadIdx.x] =
        (static_cast<std::size_t>(row) < m && a_col < k)
            ? a[static_cast<std::size_t>(row) * k + a_col]
            : 0.0f;
    tile_b[threadIdx.y][threadIdx.x] =
        (b_row < k && static_cast<std::size_t>(col) < n)
            ? b[b_row * n + static_cast<std::size_t>(col)]
            : 0.0f;

    __syncthreads();
    for (int inner = 0; inner < kTile; ++inner) {
      acc = fmaf(tile_a[threadIdx.y][inner], tile_b[inner][threadIdx.x], acc);
    }
    __syncthreads();
  }

  if (static_cast<std::size_t>(row) < m &&
      static_cast<std::size_t>(col) < n) {
    c[static_cast<std::size_t>(row) * n + static_cast<std::size_t>(col)] = acc;
  }
}

}  // namespace

void launch_gemm_fp32(const float* a, const float* b, float* c, std::size_t m,
                      std::size_t n, std::size_t k, void* stream) {
  if (m == 0 || n == 0 || k == 0) {
    return;
  }

  const dim3 block(kTile, kTile);
  const dim3 grid(static_cast<unsigned int>((n + kTile - 1) / kTile),
                  static_cast<unsigned int>((m + kTile - 1) / kTile));
  gemm_fp32_tiled_kernel<<<grid, block, 0, reinterpret_cast<cudaStream_t>(stream)>>>(
      a, b, c, m, n, k);
  CUDA_CHECK_LAST_ERROR();
}

}  // namespace cuda_kernels
