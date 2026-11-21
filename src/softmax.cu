#include "cuda_kernels/softmax.cuh"

#include <cstddef>

#include <cuda_runtime.h>
#include <math_constants.h>

#include "cuda_check.h"

namespace cuda_kernels {
namespace {

constexpr int kBlockSize = 256;
constexpr int kWarpSize = 32;
constexpr int kWarpsPerBlock = kBlockSize / kWarpSize;
static_assert(kBlockSize % kWarpSize == 0, "block size must be a whole number of warps");

__device__ __forceinline__ float warp_reduce_max(float value) {
  for (int offset = kWarpSize / 2; offset > 0; offset >>= 1) {
    value = fmaxf(value, __shfl_down_sync(0xffffffffu, value, offset));
  }
  return value;
}

__device__ __forceinline__ float warp_reduce_sum(float value) {
  for (int offset = kWarpSize / 2; offset > 0; offset >>= 1) {
    value += __shfl_down_sync(0xffffffffu, value, offset);
  }
  return value;
}

__device__ __forceinline__ float block_reduce_max(float value, float* warp_values) {
  const int lane = threadIdx.x % kWarpSize;
  const int warp = threadIdx.x / kWarpSize;
  value = warp_reduce_max(value);
  if (lane == 0) {
    warp_values[warp] = value;
  }
  __syncthreads();

  float block_value = threadIdx.x < kWarpsPerBlock ? warp_values[lane] : -CUDART_INF_F;
  if (threadIdx.x < kWarpSize) {
    block_value = warp_reduce_max(block_value);
  }
  return block_value;
}

__device__ __forceinline__ float block_reduce_sum(float value, float* warp_values) {
  const int lane = threadIdx.x % kWarpSize;
  const int warp = threadIdx.x / kWarpSize;
  value = warp_reduce_sum(value);
  if (lane == 0) {
    warp_values[warp] = value;
  }
  __syncthreads();

  float block_value = threadIdx.x < kWarpsPerBlock ? warp_values[lane] : 0.0f;
  if (threadIdx.x < kWarpSize) {
    block_value = warp_reduce_sum(block_value);
  }
  return block_value;
}

__global__ void softmax_rows_kernel(const float* __restrict__ input,
                                    float* __restrict__ output, std::size_t columns) {
  __shared__ float warp_values[kWarpsPerBlock];
  const std::size_t row_offset = static_cast<std::size_t>(blockIdx.x) * columns;

  float local_max = -CUDART_INF_F;
  for (std::size_t col = threadIdx.x; col < columns;
       col += static_cast<std::size_t>(blockDim.x)) {
    local_max = fmaxf(local_max, input[row_offset + col]);
  }
  const float max_result = block_reduce_max(local_max, warp_values);
  if (threadIdx.x == 0) {
    warp_values[0] = max_result;
  }
  __syncthreads();
  const float row_max = warp_values[0];

  float local_sum = 0.0f;
  for (std::size_t col = threadIdx.x; col < columns;
       col += static_cast<std::size_t>(blockDim.x)) {
    local_sum += expf(input[row_offset + col] - row_max);
  }
  const float sum_result = block_reduce_sum(local_sum, warp_values);
  if (threadIdx.x == 0) {
    warp_values[0] = sum_result;
  }
  __syncthreads();
  const float row_sum = warp_values[0];

  for (std::size_t col = threadIdx.x; col < columns;
       col += static_cast<std::size_t>(blockDim.x)) {
    output[row_offset + col] = expf(input[row_offset + col] - row_max) / row_sum;
  }
}

}  // namespace

void launch_softmax(const float* input, float* output, std::size_t rows,
                    std::size_t columns, void* stream) {
  if (rows == 0 || columns == 0) {
    return;
  }
  softmax_rows_kernel<<<static_cast<unsigned int>(rows), kBlockSize, 0,
                        reinterpret_cast<cudaStream_t>(stream)>>>(input, output, columns);
  CUDA_CHECK_LAST_ERROR();
}

}  // namespace cuda_kernels
