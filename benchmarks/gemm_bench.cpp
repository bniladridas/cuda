#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "bench.h"
#include "cuda_kernels/gemm.cuh"
#include "device_status.h"
#include "host_utils.h"

namespace {

struct Shape {
  std::size_t m;
  std::size_t n;
  std::size_t k;
};

bool run_case(const Shape& shape, bench::Stats* stats) {
  const auto a = host::random_floats(shape.m * shape.k, -1.0f, 1.0f, 101u);
  const auto b = host::random_floats(shape.k * shape.n, -1.0f, 1.0f, 103u);
  const auto expected = host::gemm_fp32_reference(a, b, shape.m, shape.n, shape.k);

  float *d_a = nullptr, *d_b = nullptr, *d_c = nullptr;
  if (!bench::check_cuda(cudaMalloc(&d_a, a.size() * sizeof(float)), "cudaMalloc A") ||
      !bench::check_cuda(cudaMalloc(&d_b, b.size() * sizeof(float)), "cudaMalloc B") ||
      !bench::check_cuda(cudaMalloc(&d_c, expected.size() * sizeof(float)),
                         "cudaMalloc C")) {
    if (d_a) cudaFree(d_a);
    if (d_b) cudaFree(d_b);
    if (d_c) cudaFree(d_c);
    return false;
  }

  bool ok = bench::check_cuda(cudaMemcpy(d_a, a.data(), a.size() * sizeof(float),
                                         cudaMemcpyHostToDevice),
                              "copy A") &&
            bench::check_cuda(cudaMemcpy(d_b, b.data(), b.size() * sizeof(float),
                                         cudaMemcpyHostToDevice),
                              "copy B");
  if (ok) {
    cuda_kernels::launch_gemm_fp32(d_a, d_b, d_c, shape.m, shape.n, shape.k, nullptr);
    ok = bench::check_cuda(cudaGetLastError(), "GEMM correctness launch") &&
         bench::check_cuda(cudaDeviceSynchronize(), "GEMM correctness sync");
  }

  std::vector<float> got(expected.size());
  if (ok) {
    ok = bench::check_cuda(
        cudaMemcpy(got.data(), d_c, got.size() * sizeof(float), cudaMemcpyDeviceToHost),
        "copy C");
  }
  constexpr double tolerance = 2.0e-4;
  for (std::size_t i = 0; ok && i < got.size(); ++i) {
    const double scale = std::max(1.0, std::fabs(static_cast<double>(expected[i])));
    ok = std::fabs(static_cast<double>(got[i]) - expected[i]) <= tolerance * scale;
  }

  if (ok) {
    ok = bench::measure(
        [&] {
          cuda_kernels::launch_gemm_fp32(d_a, d_b, d_c, shape.m, shape.n, shape.k,
                                         nullptr);
        },
        100, 7, 20, stats);
  }

  const bool free_a = bench::check_cuda(cudaFree(d_a), "cudaFree A");
  const bool free_b = bench::check_cuda(cudaFree(d_b), "cudaFree B");
  const bool free_c = bench::check_cuda(cudaFree(d_c), "cudaFree C");
  return ok && free_a && free_b && free_c;
}

}  // namespace

int main() {
  int devices = 0;
  const cudaError_t status = cudaGetDeviceCount(&devices);
  const auto availability =
      cuda_device::classify_device_count(status, devices, cudaSuccess, cudaErrorNoDevice);
  if (availability == cuda_device::Availability::kUnavailable) {
    std::printf("SKIPPED [gemm-benchmark]: no CUDA device\n");
    return 2;
  }
  if (availability == cuda_device::Availability::kError) {
    std::fprintf(stderr, "cudaGetDeviceCount failed: %s\n", cudaGetErrorString(status));
    return 1;
  }

  int device = 0, runtime = 0, driver = 0;
  cudaDeviceProp prop{};
  if (!bench::check_cuda(cudaGetDevice(&device), "cudaGetDevice") ||
      !bench::check_cuda(cudaGetDeviceProperties(&prop, device),
                         "cudaGetDeviceProperties") ||
      !bench::check_cuda(cudaRuntimeGetVersion(&runtime), "cudaRuntimeGetVersion") ||
      !bench::check_cuda(cudaDriverGetVersion(&driver), "cudaDriverGetVersion")) {
    return 1;
  }

  const Shape shapes[] = {{64, 64, 64}, {127, 193, 65}, {256, 256, 256}};
  bench::Stats results[3];
  for (std::size_t i = 0; i < 3; ++i) {
    if (!run_case(shapes[i], &results[i])) {
      std::fprintf(stderr, "GEMM correctness or timing failed for M=%zu N=%zu K=%zu\n",
                   shapes[i].m, shapes[i].n, shapes[i].k);
      return 1;
    }
  }

  std::printf("{\n  \"gpu\": \"%s\",\n", prop.name);
  std::printf("  \"compute_capability\": \"%d.%d\",\n", prop.major, prop.minor);
  std::printf("  \"driver_version\": %d,\n  \"cuda_runtime_version\": %d,\n", driver,
              runtime);
  std::printf("  \"tile\": [16, 16],\n  \"results\": [\n");
  for (std::size_t i = 0; i < 3; ++i) {
    const auto& s = shapes[i];
    const auto& r = results[i];
    std::printf("    {\"M\": %zu, \"N\": %zu, \"K\": %zu, "
                "\"median_ms\": %.6f, \"min_ms\": %.6f, \"p90_ms\": %.6f}%s\n",
                s.m, s.n, s.k, r.median_ms, r.min_ms, r.p90_ms, i == 2 ? "" : ",");
  }
  std::printf("  ]\n}\n");
  return 0;
}
