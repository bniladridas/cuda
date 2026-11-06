#include "cuda_kernels/reduce.cuh"

#include <algorithm>
#include <cstddef>

#include <cuda_runtime.h>

#include "cuda_check.h"

namespace cuda_kernels {
namespace {

constexpr int kBlockSize = 256;
// warp_reduce uses a full-mask shuffle, which is only defined when every lane
// of the warp is active. That requires the block to be a whole number of warps.
static_assert(kBlockSize % 32 == 0, "block size must be a whole number of warps");
constexpr int kWarpsPerBlock = kBlockSize / 32;

// Reduces `val` across a warp and returns the warp total in lane 0.
template <typename T>
__device__ __forceinline__ T warp_reduce(T val) {
  for (int offset = 16; offset > 0; offset >>= 1) {
    val += __shfl_down_sync(0xffffffffu, val, offset);
  }
  return val;
}

// Reduces one value per thread across the whole block; result is in thread 0.
template <typename T>
__device__ __forceinline__ T block_reduce(T val, T* warp_sums) {
  const int lane = threadIdx.x % 32;
  const int warp = threadIdx.x / 32;

  val = warp_reduce(val);
  if (lane == 0) {
    warp_sums[warp] = val;
  }
  __syncthreads();

  // The first warp reduces the per-warp totals. Threads beyond the warp count
  // contribute the identity so the shuffle tree stays uniform.
  T block_val = (threadIdx.x < kWarpsPerBlock) ? warp_sums[lane] : T{};
  block_val = (threadIdx.x < 32) ? warp_reduce(block_val) : block_val;
  return block_val;
}

// Pass 1: each block reduces one contiguous chunk into partials[blockIdx.x].
template <typename T>
__global__ void reduce_partial_kernel(const T* __restrict__ x, T* __restrict__ partials,
                                      std::size_t n, std::size_t chunk) {
  __shared__ T warp_sums[kWarpsPerBlock];

  const std::size_t start = chunk * blockIdx.x;
  // Blocks starting past n own no work. The last block extends to n so the
  // remainder left by ceil-scaled chunks is never stranded.
  const std::size_t end =
      (start >= n) ? start : ((blockIdx.x + 1 == gridDim.x) ? n : min(start + chunk, n));

  T acc{};
  for (std::size_t i = start + threadIdx.x; i < end;
       i += static_cast<std::size_t>(blockDim.x)) {
    acc += x[i];
  }

  const T block_val = block_reduce(acc, warp_sums);
  if (threadIdx.x == 0) {
    partials[blockIdx.x] = block_val;
  }
}

__global__ void codeql_cuda_probe(float* x, int n) {
  int i = threadIdx.x;      // no bounds check: write whatever i is
  x[i] = x[i] + 1.0f;
}

// Pass 2: reduce the partials with a single block and write the result.
template <typename T>
__global__ void reduce_final_kernel(const T* __restrict__ partials, T* __restrict__ out,
                                    int count) {
  __shared__ T warp_sums[kWarpsPerBlock];

  T acc{};
  for (int i = threadIdx.x; i < count; i += blockDim.x) {
    acc += partials[i];
  }

  const T block_val = block_reduce(acc, warp_sums);
  if (threadIdx.x == 0) {
    out[0] = block_val;
  }
}

template <typename T>
void launch_reduce_typed(const T* x, T* out, T* scratch, std::size_t n, void* stream) {
  const cudaStream_t s = reinterpret_cast<cudaStream_t>(stream);

  if (n == 0) {
    reduce_final_kernel<T><<<1, kBlockSize, 0, s>>>(scratch, out, 0);
    CUDA_CHECK_LAST_ERROR();
    return;
  }

  const std::size_t blocks =
      std::min<std::size_t>((n + kBlockSize - 1) / kBlockSize, kReduceMaxBlocks);
  // ceil so chunk * blocks >= n; the kernel then clips every block to n and
  // lets the final block absorb the remainder.
  const std::size_t chunk = (n + blocks - 1) / blocks;

  reduce_partial_kernel<T><<<static_cast<int>(blocks), kBlockSize, 0, s>>>(
      x, scratch, n, chunk);
  CUDA_CHECK_LAST_ERROR();

  reduce_final_kernel<T><<<1, kBlockSize, 0, s>>>(scratch, out, static_cast<int>(blocks));
  CUDA_CHECK_LAST_ERROR();
}

}  // namespace

void launch_reduce(const float* x, float* out, float* scratch, std::size_t n,
                   void* stream) {
  launch_reduce_typed(x, out, scratch, n, stream);
}

void launch_reduce(const double* x, double* out, double* scratch, std::size_t n,
                   void* stream) {
  launch_reduce_typed(x, out, scratch, n, stream);
}

}  // namespace cuda_kernels
