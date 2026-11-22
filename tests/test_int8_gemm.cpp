#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "cuda_kernels/int8_gemm.cuh"
#include "device_status.h"
#include "host_utils.h"
#include "int8_gemm_reference.h"

namespace {

const char* const kTest = "int8-gemm";

#define CHECK_CUDA(expr)                                                     \
  do {                                                                       \
    cudaError_t err__ = (expr);                                              \
    host::check(err__ == cudaSuccess, kTest,                                 \
                std::string(#expr " failed: ") + cudaGetErrorString(err__)); \
  } while (0)

void run_case(const std::vector<std::int8_t>& a,
              const std::vector<std::int8_t>& b, std::size_t m,
              std::size_t n, std::size_t k, const char* label) {
  const auto expected = host::gemm_int8_reference(a, b, m, n, k);
  host::check(expected.size() == m * n, kTest, "invalid CPU reference result");
  std::vector<std::int32_t> got(expected.size());
  std::int8_t *d_a = nullptr, *d_b = nullptr;
  std::int32_t* d_c = nullptr;
  CHECK_CUDA(cudaMalloc(&d_a, a.size() * sizeof(std::int8_t)));
  CHECK_CUDA(cudaMalloc(&d_b, b.size() * sizeof(std::int8_t)));
  CHECK_CUDA(cudaMalloc(&d_c, got.size() * sizeof(std::int32_t)));
  CHECK_CUDA(cudaMemcpy(d_a, a.data(), a.size() * sizeof(std::int8_t),
                        cudaMemcpyHostToDevice));
  CHECK_CUDA(cudaMemcpy(d_b, b.data(), b.size() * sizeof(std::int8_t),
                        cudaMemcpyHostToDevice));
  cuda_kernels::launch_gemm_int8(d_a, d_b, d_c, m, n, k, nullptr);
  CHECK_CUDA(cudaDeviceSynchronize());
  CHECK_CUDA(cudaMemcpy(got.data(), d_c, got.size() * sizeof(std::int32_t),
                        cudaMemcpyDeviceToHost));
  host::check(got == expected, kTest, std::string("integer mismatch: ") + label);
  std::printf("PASS [%s] M=%zu N=%zu K=%zu (%s)\n", kTest, m, n, k, label);
  CHECK_CUDA(cudaFree(d_a));
  CHECK_CUDA(cudaFree(d_b));
  CHECK_CUDA(cudaFree(d_c));
}

void run_stream_case() {
  constexpr std::size_t m = 3, n = 5, k = 7;
  const std::vector<std::int8_t> a(m * k, static_cast<std::int8_t>(-3));
  const std::vector<std::int8_t> b(k * n, static_cast<std::int8_t>(4));
  const auto expected = host::gemm_int8_reference(a, b, m, n, k);
  std::vector<std::int32_t> got(expected.size());
  std::int8_t *d_a = nullptr, *d_b = nullptr;
  std::int32_t* d_c = nullptr;
  cudaStream_t stream = nullptr;
  CHECK_CUDA(cudaStreamCreate(&stream));
  CHECK_CUDA(cudaMalloc(&d_a, a.size() * sizeof(std::int8_t)));
  CHECK_CUDA(cudaMalloc(&d_b, b.size() * sizeof(std::int8_t)));
  CHECK_CUDA(cudaMalloc(&d_c, got.size() * sizeof(std::int32_t)));
  CHECK_CUDA(cudaMemcpyAsync(d_a, a.data(), a.size(), cudaMemcpyHostToDevice, stream));
  CHECK_CUDA(cudaMemcpyAsync(d_b, b.data(), b.size(), cudaMemcpyHostToDevice, stream));
  cuda_kernels::launch_gemm_int8(d_a, d_b, d_c, m, n, k,
                                 reinterpret_cast<void*>(stream));
  CHECK_CUDA(cudaMemcpyAsync(got.data(), d_c, got.size() * sizeof(std::int32_t),
                             cudaMemcpyDeviceToHost, stream));
  CHECK_CUDA(cudaStreamSynchronize(stream));
  host::check(got == expected, kTest, "non-default stream mismatch");
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

  run_case({-128, 127, -1, 0, 1, 64}, {127, -128, 1, 0, -1, 32}, 1, 1, 6,
           "signed-range");
  run_case(std::vector<std::int8_t>(17 * 23, static_cast<std::int8_t>(-128)),
           std::vector<std::int8_t>(23 * 19, static_cast<std::int8_t>(127)),
           17, 19, 23, "irregular-extremes");
  run_case(std::vector<std::int8_t>(1, static_cast<std::int8_t>(-128)),
           std::vector<std::int8_t>(1, static_cast<std::int8_t>(-128)),
           1, 1, 1, "single-element");
  run_stream_case();
  std::printf("OK [%s] all cases passed\n", kTest);
  return 0;
}
