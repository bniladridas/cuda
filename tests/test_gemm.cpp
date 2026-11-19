#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "cuda_kernels/gemm.cuh"
#include "device_status.h"
#include "host_utils.h"

namespace {

const char* const kTest = "gemm";
constexpr double kTolerance = 2.0e-4;

#define CHECK_CUDA(expr)                                                     \
  do {                                                                       \
    cudaError_t err__ = (expr);                                              \
    host::check(err__ == cudaSuccess, kTest,                                 \
                std::string(#expr " failed: ") + cudaGetErrorString(err__)); \
  } while (0)

void run_case(std::size_t m, std::size_t n, std::size_t k, const char* label) {
  const std::vector<float> a = host::random_floats(m * k, -1.0f, 1.0f, 17u);
  const std::vector<float> b = host::random_floats(k * n, -1.0f, 1.0f, 29u);
  const std::vector<float> expected = host::gemm_fp32_reference(a, b, m, n, k);

  float* d_a = nullptr;
  float* d_b = nullptr;
  float* d_c = nullptr;
  CHECK_CUDA(cudaMalloc(&d_a, a.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_b, b.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_c, expected.size() * sizeof(float)));
  CHECK_CUDA(cudaMemcpy(d_a, a.data(), a.size() * sizeof(float), cudaMemcpyHostToDevice));
  CHECK_CUDA(cudaMemcpy(d_b, b.data(), b.size() * sizeof(float), cudaMemcpyHostToDevice));

  cuda_kernels::launch_gemm_fp32(d_a, d_b, d_c, m, n, k, nullptr);
  CHECK_CUDA(cudaDeviceSynchronize());

  std::vector<float> got(expected.size());
  CHECK_CUDA(
      cudaMemcpy(got.data(), d_c, got.size() * sizeof(float), cudaMemcpyDeviceToHost));
  for (std::size_t i = 0; i < got.size(); ++i) {
    const double scale = std::max(1.0, std::fabs(static_cast<double>(expected[i])));
    const double error = std::fabs(static_cast<double>(got[i]) - expected[i]);
    host::check(error <= kTolerance * scale, kTest,
                std::string("mismatch at output ") + std::to_string(i) + " (" + label +
                    "), got " + std::to_string(got[i]) + " expected " +
                    std::to_string(expected[i]));
  }

  std::printf("PASS [%s] M=%zu N=%zu K=%zu (%s)\n", kTest, m, n, k, label);
  CHECK_CUDA(cudaFree(d_a));
  CHECK_CUDA(cudaFree(d_b));
  CHECK_CUDA(cudaFree(d_c));
}

void run_non_default_stream_case() {
  constexpr std::size_t m = 19, n = 23, k = 21;
  const std::vector<float> a = host::random_floats(m * k, -1.0f, 1.0f, 31u);
  const std::vector<float> b = host::random_floats(k * n, -1.0f, 1.0f, 37u);
  const auto expected = host::gemm_fp32_reference(a, b, m, n, k);
  std::vector<float> got(expected.size());
  float *d_a = nullptr, *d_b = nullptr, *d_c = nullptr;
  cudaStream_t stream = nullptr;
  CHECK_CUDA(cudaStreamCreate(&stream));
  CHECK_CUDA(cudaMalloc(&d_a, a.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_b, b.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_c, got.size() * sizeof(float)));
  CHECK_CUDA(cudaMemcpyAsync(d_a, a.data(), a.size() * sizeof(float),
                             cudaMemcpyHostToDevice, stream));
  CHECK_CUDA(cudaMemcpyAsync(d_b, b.data(), b.size() * sizeof(float),
                             cudaMemcpyHostToDevice, stream));
  cuda_kernels::launch_gemm_fp32(d_a, d_b, d_c, m, n, k, reinterpret_cast<void*>(stream));
  CHECK_CUDA(cudaMemcpyAsync(got.data(), d_c, got.size() * sizeof(float),
                             cudaMemcpyDeviceToHost, stream));
  CHECK_CUDA(cudaStreamSynchronize(stream));
  for (std::size_t i = 0; i < got.size(); ++i) {
    const double scale = std::max(1.0, std::fabs(static_cast<double>(expected[i])));
    host::check(std::fabs(static_cast<double>(got[i]) - expected[i]) <=
                    kTolerance * scale,
                kTest, "non-default stream result mismatch");
  }
  std::printf("PASS [%s] non-default stream\n", kTest);
  CHECK_CUDA(cudaStreamDestroy(stream));
  CHECK_CUDA(cudaFree(d_a));
  CHECK_CUDA(cudaFree(d_b));
  CHECK_CUDA(cudaFree(d_c));
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
    std::fprintf(stderr, "ERROR [%s]: cudaGetDeviceCount failed: %s\n", kTest,
                 cudaGetErrorString(status));
    return 1;
  }

  run_case(1, 1, 1, "single-element");
  run_case(3, 5, 7, "small-rectangular");
  run_case(16, 16, 16, "one-tile");
  run_case(17, 19, 23, "partial-edge-tiles");
  run_case(31, 7, 33, "tall-rectangular");
  run_case(7, 35, 17, "wide-rectangular");
  run_case(64, 48, 65, "K-edge");
  run_non_default_stream_case();
  std::printf("OK [%s] all cases passed\n", kTest);
  return 0;
}
