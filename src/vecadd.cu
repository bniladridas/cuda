#include "cuda_kernels/vecadd.cuh"

#include <algorithm>
#include <cstddef>

#include <cuda_runtime.h>

#include "cuda_check.h"

namespace cuda_kernels {
namespace {

constexpr int kBlockSize = 256;
constexpr int kMaxBlocks = 65535;

__global__ void vecadd_kernel(const float* __restrict__ a,
                              const float* __restrict__ b, float* __restrict__ c,
                              std::size_t n) {
  const std::size_t stride = static_cast<std::size_t>(blockDim.x) * gridDim.x;
  for (std::size_t i = static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
       i < n; i += stride) {
    c[i] = a[i] + b[i];
  }
}

}  // namespace

void launch_vecadd(const float* a, const float* b, float* c, std::size_t n,
                   void* stream) {
  if (n == 0) {
    return;
  }
  const std::size_t needed = (n + kBlockSize - 1) / kBlockSize;
  const int blocks = static_cast<int>(std::min<std::size_t>(needed, kMaxBlocks));
  vecadd_kernel<<<blocks, kBlockSize, 0, reinterpret_cast<cudaStream_t>(stream)>>>(
      a, b, c, n);
  CUDA_CHECK_LAST_ERROR();
}

}  // namespace cuda_kernels
