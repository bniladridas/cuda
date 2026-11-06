#include <cstddef>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "cuda_kernels/vecadd.cuh"
#include "host_utils.h"

namespace {

const char* const kTest = "vecadd";

#define CHECK_CUDA(expr)                                                          \
  do {                                                                            \
    cudaError_t err__ = (expr);                                                   \
    host::check(err__ == cudaSuccess, kTest,                                      \
                std::string(#expr " failed: ") + cudaGetErrorString(err__));      \
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

}  // namespace

int main() {
  int devices = 0;
  if (cudaGetDeviceCount(&devices) != cudaSuccess || devices == 0) {
    std::printf("SKIPPED [%s]: no CUDA device\n", kTest);
    return 0;
  }

  // 0 (no-op), 1 (sub-warp), 255/256/257 (block boundary), 1Mi (grid stride),
  // plus an odd size that is a multiple of nothing convenient.
  run_case(0, "empty");
  run_case(1, "single");
  run_case(255, "block-1");
  run_case(256, "block");
  run_case(257, "block+1");
  run_case(1000003, "odd-large");
  run_case(1u << 20, "1Mi");

  std::printf("OK [%s] all cases passed\n", kTest);
  return 0;
}
