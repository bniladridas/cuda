#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "attention_reference.h"
#include "cuda_kernels/attention.cuh"
#include "device_status.h"
#include "host_utils.h"

namespace {
const char* const kTest = "attention";
constexpr double kTolerance = 8.0e-4;

#define CHECK_CUDA(expr)                                                       \
  do {                                                                         \
    cudaError_t error__ = (expr);                                              \
    host::check(error__ == cudaSuccess, kTest,                                 \
                std::string(#expr " failed: ") + cudaGetErrorString(error__)); \
  } while (0)

void run_case(std::size_t lq, std::size_t lk, std::size_t d, std::size_t dv,
              unsigned seed, const char* label, bool challenging = false) {
  const auto q = host::random_floats(lq * d, -2.0f, 2.0f, seed);
  auto k = host::random_floats(lk * d, -2.0f, 2.0f, seed + 1);
  const auto v = host::random_floats(lk * dv, -2.0f, 2.0f, seed + 2);
  if (challenging) {
    for (float& value : k) value *= 40.0f;
  }
  const auto expected = host::attention_reference(q, k, v, lq, lk, d, dv);
  const std::size_t score_count = lq * lk;
  float *dq = nullptr, *dk = nullptr, *dv_ptr = nullptr, *dout = nullptr;
  float *dscores = nullptr, *dprobabilities = nullptr;
  CHECK_CUDA(cudaMalloc(&dq, q.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&dk, k.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&dv_ptr, v.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&dout, expected.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&dscores, score_count * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&dprobabilities, score_count * sizeof(float)));
  CHECK_CUDA(cudaMemcpy(dq, q.data(), q.size() * sizeof(float), cudaMemcpyHostToDevice));
  CHECK_CUDA(cudaMemcpy(dk, k.data(), k.size() * sizeof(float), cudaMemcpyHostToDevice));
  CHECK_CUDA(cudaMemcpy(dv_ptr, v.data(), v.size() * sizeof(float), cudaMemcpyHostToDevice));

  cuda_kernels::launch_attention_fp32(dq, dk, dv_ptr, dout, dscores,
                                      dprobabilities, lq, lk, d, dv, nullptr);
  CHECK_CUDA(cudaDeviceSynchronize());
  std::vector<float> got(expected.size());
  CHECK_CUDA(cudaMemcpy(got.data(), dout, got.size() * sizeof(float),
                        cudaMemcpyDeviceToHost));
  for (std::size_t i = 0; i < got.size(); ++i) {
    const double scale = std::max(1.0, std::fabs(static_cast<double>(expected[i])));
    host::check(std::isfinite(got[i]) &&
                    std::fabs(static_cast<double>(got[i]) - expected[i]) <=
                        kTolerance * scale,
                kTest, std::string(label) + ": output mismatch at " +
                           std::to_string(i));
  }
  std::printf("PASS [%s] %s Lq=%zu Lk=%zu D=%zu Dv=%zu\n",
              kTest, label, lq, lk, d, dv);
  CHECK_CUDA(cudaFree(dq));
  CHECK_CUDA(cudaFree(dk));
  CHECK_CUDA(cudaFree(dv_ptr));
  CHECK_CUDA(cudaFree(dout));
  CHECK_CUDA(cudaFree(dscores));
  CHECK_CUDA(cudaFree(dprobabilities));
}
}  // namespace

int main() {
  int devices = 0;
  const cudaError_t status = cudaGetDeviceCount(&devices);
  const auto availability =
      cuda_device::classify_device_count(status, devices, cudaSuccess, cudaErrorNoDevice);
  if (availability == cuda_device::Availability::kUnavailable) {
    std::printf("SKIPPED [%s]: no CUDA device\n", kTest);
    return 0;
  }
  if (availability == cuda_device::Availability::kError) {
    std::fprintf(stderr, "ERROR [%s]: %s\n", kTest, cudaGetErrorString(status));
    return 1;
  }
  run_case(2, 3, 5, 7, 31u, "unequal-irregular");
  run_case(3, 5, 17, 11, 41u, "non-multiple-dimensions");
  run_case(1, 1, 1, 1, 51u, "single-element");
  run_case(2, 4, 8, 3, 61u, "challenging-logits", true);
  std::printf("OK [%s] all cases passed\n", kTest);
  return 0;
}
