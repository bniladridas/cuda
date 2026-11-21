#include <cstddef>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "cuda_kernels/vecadd.cuh"
#include "device_status.h"
#include "host_utils.h"

namespace {

const char* const kTest = "vecadd";

#define CHECK_CUDA(expr)                                                     \
  do {                                                                       \
    cudaError_t err__ = (expr);                                              \
    host::check(err__ == cudaSuccess, kTest,                                 \
                std::string(#expr " failed: ") + cudaGetErrorString(err__)); \
  } while (0)

void run_case(std::size_t n, const char* label) {
  const std::vector<float> a = host::random_floats(n, -100.0f, 100.0f, 11u);
  const std::vector<float> b = host::random_floats(n, -100.0f, 100.0f, 22u);
  const std::vector<float> expected = host::vecadd_reference(a, b);

  float* d_a = nullptr;
  float* d_b = nullptr;
  float* d_c = nullptr;
  // cudaMalloc(nullptr, 0) is rejected; allocate one element so the zero-length
  // case exercises the launcher's early return rather than the allocator.
  const std::size_t alloc = n == 0 ? 1 : n;
  CHECK_CUDA(cudaMalloc(&d_a, alloc * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_b, alloc * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_c, alloc * sizeof(float)));

  if (n > 0) {
    CHECK_CUDA(cudaMemcpy(d_a, a.data(), n * sizeof(float), cudaMemcpyHostToDevice));
    CHECK_CUDA(cudaMemcpy(d_b, b.data(), n * sizeof(float), cudaMemcpyHostToDevice));
    CHECK_CUDA(cudaMemset(d_c, 0xFF, n * sizeof(float)));
  }

  cuda_kernels::launch_vecadd(d_a, d_b, d_c, n, nullptr);
  CHECK_CUDA(cudaDeviceSynchronize());

  if (n == 0) {
    std::printf("PASS [%s] n=0 (%s)\n", kTest, label);
  } else {
    std::vector<float> got(n);
    CHECK_CUDA(cudaMemcpy(got.data(), d_c, n * sizeof(float), cudaMemcpyDeviceToHost));
    for (std::size_t i = 0; i < n; ++i) {
      host::check(std::memcmp(&got[i], &expected[i], sizeof(float)) == 0, kTest,
                  std::string("mismatch at ") + std::to_string(i) + " (" + label +
                      ") got " + std::to_string(got[i]) + " expected " +
                      std::to_string(expected[i]));
    }
    std::printf("PASS [%s] n=%zu (%s)\n", kTest, n, label);
  }

  CHECK_CUDA(cudaFree(d_a));
  CHECK_CUDA(cudaFree(d_b));
  CHECK_CUDA(cudaFree(d_c));
}

void run_null_zero_length_case() {
  // The public contract promises that all three data pointers are untouched
  // when n == 0. Exercise both the default and an explicit stream.
  cuda_kernels::launch_vecadd(nullptr, nullptr, nullptr, 0, nullptr);
  CHECK_CUDA(cudaDeviceSynchronize());

  cudaStream_t stream = nullptr;
  CHECK_CUDA(cudaStreamCreate(&stream));
  cuda_kernels::launch_vecadd(nullptr, nullptr, nullptr, 0,
                              reinterpret_cast<void*>(stream));
  CHECK_CUDA(cudaStreamSynchronize(stream));
  CHECK_CUDA(cudaStreamDestroy(stream));
  std::printf("PASS [%s] n=0 (all-null-pointers, default-and-explicit-stream)\n", kTest);
}

void run_non_default_stream_case() {
  constexpr std::size_t n = 100003;
  const std::vector<float> a = host::random_floats(n, -100.0f, 100.0f, 31u);
  const std::vector<float> b = host::random_floats(n, -100.0f, 100.0f, 32u);
  const std::vector<float> expected = host::vecadd_reference(a, b);
  std::vector<float> got(n);

  float* d_a = nullptr;
  float* d_b = nullptr;
  float* d_c = nullptr;
  cudaStream_t stream = nullptr;
  CHECK_CUDA(cudaStreamCreate(&stream));
  CHECK_CUDA(cudaMalloc(&d_a, n * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_b, n * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_c, n * sizeof(float)));

  // Keep transfers, kernel launch, and result retrieval in one non-default
  // stream so the test checks the public stream argument and its ordering.
  CHECK_CUDA(
      cudaMemcpyAsync(d_a, a.data(), n * sizeof(float), cudaMemcpyHostToDevice, stream));
  CHECK_CUDA(
      cudaMemcpyAsync(d_b, b.data(), n * sizeof(float), cudaMemcpyHostToDevice, stream));
  cuda_kernels::launch_vecadd(d_a, d_b, d_c, n, reinterpret_cast<void*>(stream));
  CHECK_CUDA(cudaMemcpyAsync(got.data(), d_c, n * sizeof(float), cudaMemcpyDeviceToHost,
                             stream));
  CHECK_CUDA(cudaStreamSynchronize(stream));

  for (std::size_t i = 0; i < n; ++i) {
    host::check(std::memcmp(&got[i], &expected[i], sizeof(float)) == 0, kTest,
                std::string("non-default stream mismatch at ") + std::to_string(i));
  }
  std::printf("PASS [%s] n=%zu (non-default-stream)\n", kTest, n);

  CHECK_CUDA(cudaStreamDestroy(stream));
  CHECK_CUDA(cudaFree(d_a));
  CHECK_CUDA(cudaFree(d_b));
  CHECK_CUDA(cudaFree(d_c));
}

}  // namespace

int main() {
  int devices = 0;
  const cudaError_t device_status = cudaGetDeviceCount(&devices);
  const cuda_device::Availability availability = cuda_device::classify_device_count(
      device_status, devices, cudaSuccess, cudaErrorNoDevice);
  if (availability == cuda_device::Availability::kUnavailable) {
    std::printf("SKIPPED [%s]: no CUDA device\n", kTest);
    return 0;
  }
  if (availability == cuda_device::Availability::kError) {
    std::fprintf(stderr, "ERROR [%s]: cudaGetDeviceCount failed: %s\n", kTest,
                 cudaGetErrorString(device_status));
    return 1;
  }

  // 0 (no-op), 1 (sub-warp), 255/256/257 (block boundary), 1Mi (grid stride),
  // plus an odd size that is a multiple of nothing convenient.
  run_case(0, "empty");
  run_null_zero_length_case();
  run_case(1, "single");
  run_case(255, "block-1");
  run_case(256, "block");
  run_case(257, "block+1");
  run_case(1000003, "odd-large");
  run_case(1u << 20, "1Mi");
  run_non_default_stream_case();

  std::printf("OK [%s] all cases passed\n", kTest);
  return 0;
}
