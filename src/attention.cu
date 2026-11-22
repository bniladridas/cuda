#include "cuda_kernels/attention.cuh"

#include <cstddef>
#include <cstdint>

#include <cuda_runtime.h>

#include "cuda_check.h"
#include "cuda_kernels/softmax.cuh"

namespace cuda_kernels {
namespace {

constexpr unsigned int kBlockSize = 256;
constexpr std::size_t kMaxGridX = 2147483647ULL;
constexpr std::size_t kMaxGridY = 65535ULL;

__global__ void attention_scores_kernel(const float* __restrict__ q,
                                        const float* __restrict__ k,
                                        float* __restrict__ scores, std::size_t lq,
                                        std::size_t lk, std::size_t d, float scale) {
  const std::size_t row = blockIdx.y;
  const std::size_t col = static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
  if (row >= lq || col >= lk) return;

  float acc = 0.0f;
  for (std::size_t inner = 0; inner < d; ++inner) {
    acc = fmaf(q[row * d + inner], k[col * d + inner], acc);
  }
  scores[row * lk + col] = acc * scale;
}

__global__ void attention_values_kernel(const float* __restrict__ probabilities,
                                        const float* __restrict__ v,
                                        float* __restrict__ output, std::size_t lq,
                                        std::size_t lk, std::size_t dv) {
  const std::size_t row = blockIdx.y;
  const std::size_t col = static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
  if (row >= lq || col >= dv) return;

  float acc = 0.0f;
  for (std::size_t key = 0; key < lk; ++key) {
    acc = fmaf(probabilities[row * lk + key], v[key * dv + col], acc);
  }
  output[row * dv + col] = acc;
}

}  // namespace

void launch_attention_fp32(const float* q, const float* k, const float* v,
                           float* output, float* scores, float* probabilities,
                           std::size_t lq, std::size_t lk, std::size_t d,
                           std::size_t dv, void* stream) {
  if (lq == 0 || lk == 0 || d == 0 || dv == 0) return;

  CUDA_CHECK(lq <= kMaxGridY && (lk + kBlockSize - 1) / kBlockSize <= kMaxGridX &&
             (dv + kBlockSize - 1) / kBlockSize <= kMaxGridX
                 ? cudaSuccess
                 : cudaErrorInvalidValue);

  const cudaStream_t cuda_stream = reinterpret_cast<cudaStream_t>(stream);
  const dim3 score_grid(static_cast<unsigned int>((lk + kBlockSize - 1) / kBlockSize),
                        static_cast<unsigned int>(lq));
  const dim3 value_grid(static_cast<unsigned int>((dv + kBlockSize - 1) / kBlockSize),
                        static_cast<unsigned int>(lq));
  attention_scores_kernel<<<score_grid, kBlockSize, 0, cuda_stream>>>(
      q, k, scores, lq, lk, d, rsqrtf(static_cast<float>(d)));
  CUDA_CHECK_LAST_ERROR();
  launch_softmax(scores, probabilities, lq, lk, stream);
  attention_values_kernel<<<value_grid, kBlockSize, 0, cuda_stream>>>(
      probabilities, v, output, lq, lk, dv);
  CUDA_CHECK_LAST_ERROR();
}

}  // namespace cuda_kernels
