#include "cuda_kernels/layernorm.cuh"

#include <cstddef>

#include <cuda_runtime.h>

#include "cuda_check.h"

namespace cuda_kernels {
namespace {

constexpr int kWarpSize = 32;
constexpr int kBlockSize = 256;
constexpr int kWarpsPerBlock = kBlockSize / kWarpSize;
static_assert(kBlockSize % kWarpSize == 0, "block size must be a whole number of warps");

__device__ __forceinline__ float warp_sum(float value) {
  for (int offset = kWarpSize / 2; offset > 0; offset >>= 1) {
    value += __shfl_down_sync(0xffffffffu, value, offset);
  }
  return value;
}

__device__ __forceinline__ float block_sum(float value, float* warp_sums) {
  const int lane = threadIdx.x % kWarpSize;
  const int warp = threadIdx.x / kWarpSize;
  value = warp_sum(value);
  if (lane == 0) {
    warp_sums[warp] = value;
  }
  __syncthreads();

  float total = threadIdx.x < kWarpsPerBlock ? warp_sums[lane] : 0.0f;
  if (threadIdx.x < kWarpSize) {
    total = warp_sum(total);
  }
  return total;
}

__global__ void layernorm_rows_kernel(const float* __restrict__ input,
                                      const float* __restrict__ gamma,
                                      const float* __restrict__ beta,
                                      float* __restrict__ output, std::size_t features,
                                      float epsilon) {
  __shared__ float warp_sums[kWarpsPerBlock];
  const std::size_t offset = static_cast<std::size_t>(blockIdx.x) * features;

  float local_sum = 0.0f;
  for (std::size_t col = threadIdx.x; col < features;
       col += static_cast<std::size_t>(blockDim.x)) {
    local_sum += input[offset + col];
  }
  const float sum = block_sum(local_sum, warp_sums);
  if (threadIdx.x == 0) {
    warp_sums[0] = sum / static_cast<float>(features);
  }
  __syncthreads();
  const float mean = warp_sums[0];

  float local_squared_deviation = 0.0f;
  for (std::size_t col = threadIdx.x; col < features;
       col += static_cast<std::size_t>(blockDim.x)) {
    const float delta = input[offset + col] - mean;
    local_squared_deviation = fmaf(delta, delta, local_squared_deviation);
  }
  const float squared_deviation_sum = block_sum(local_squared_deviation, warp_sums);
  if (threadIdx.x == 0) {
    warp_sums[0] = squared_deviation_sum / static_cast<float>(features);
  }
  __syncthreads();
  const float variance = warp_sums[0];
  const float inverse_stddev = rsqrtf(variance + epsilon);

  for (std::size_t col = threadIdx.x; col < features;
       col += static_cast<std::size_t>(blockDim.x)) {
    const float normalized = (input[offset + col] - mean) * inverse_stddev;
    output[offset + col] = fmaf(normalized, gamma[col], beta[col]);
  }
}

}  // namespace

void launch_layernorm_fp32(const float* input, const float* gamma, const float* beta,
                           float* output, std::size_t rows, std::size_t features,
                           float epsilon, void* stream) {
  if (rows == 0 || features == 0) {
    return;
  }
  CUDA_CHECK(detail::is_valid_layernorm_epsilon(epsilon) ? cudaSuccess
                                                         : cudaErrorInvalidValue);
  layernorm_rows_kernel<<<static_cast<unsigned int>(rows), kBlockSize, 0,
                          reinterpret_cast<cudaStream_t>(stream)>>>(
      input, gamma, beta, output, features, epsilon);
  CUDA_CHECK_LAST_ERROR();
}

}  // namespace cuda_kernels
