#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <vector>

#include <cuda_runtime.h>

#include "bench.h"
#include "cuda_kernels/int8_gemm.cuh"
#include "device_status.h"
#include "int8_gemm_reference.h"

namespace {

bool run_case(std::size_t m, std::size_t n, std::size_t k, bench::Stats* stats) {
  const std::vector<std::int8_t> a(m * k, static_cast<std::int8_t>(3));
  const std::vector<std::int8_t> b(k * n, static_cast<std::int8_t>(-2));
  const auto expected = host::gemm_int8_reference(a, b, m, n, k);
  std::vector<std::int32_t> got(expected.size());
  std::int8_t *d_a = nullptr, *d_b = nullptr;
  std::int32_t* d_c = nullptr;
  bool ok = bench::check_cuda(cudaMalloc(&d_a, a.size()), "allocate A") &&
            bench::check_cuda(cudaMalloc(&d_b, b.size()), "allocate B") &&
            bench::check_cuda(cudaMalloc(&d_c, got.size() * sizeof(std::int32_t)),
                              "allocate C");
  if (ok) ok = bench::check_cuda(cudaMemcpy(d_a, a.data(), a.size(), cudaMemcpyHostToDevice),
                                 "copy A") &&
               bench::check_cuda(cudaMemcpy(d_b, b.data(), b.size(), cudaMemcpyHostToDevice),
                                 "copy B");
  if (ok) {
    cuda_kernels::launch_gemm_int8(d_a, d_b, d_c, m, n, k, nullptr);
    ok = bench::check_cuda(cudaDeviceSynchronize(), "correctness sync") &&
         bench::check_cuda(cudaMemcpy(got.data(), d_c, got.size() * sizeof(std::int32_t),
                                      cudaMemcpyDeviceToHost), "copy C") &&
         got == expected;
  }
  if (ok) {
    ok = bench::measure([&] { cuda_kernels::launch_gemm_int8(d_a, d_b, d_c, m, n, k, nullptr); },
                        100, 7, 20, stats);
  }
  if (d_a) ok = bench::check_cuda(cudaFree(d_a), "free A") && ok;
  if (d_b) ok = bench::check_cuda(cudaFree(d_b), "free B") && ok;
  if (d_c) ok = bench::check_cuda(cudaFree(d_c), "free C") && ok;
  return ok;
}

}  // namespace

int main() {
  int devices = 0;
  const cudaError_t status = cudaGetDeviceCount(&devices);
  const auto availability =
      cuda_device::classify_device_count(status, devices, cudaSuccess, cudaErrorNoDevice);
  if (availability == cuda_device::Availability::kUnavailable) {
    std::printf("SKIPPED [int8-gemm-benchmark]: no CUDA device\n");
    return 2;
  }
  if (availability == cuda_device::Availability::kError) return 1;

  int device = 0, runtime = 0, driver = 0;
  cudaDeviceProp prop{};
  if (!bench::check_cuda(cudaGetDevice(&device), "get device") ||
      !bench::check_cuda(cudaGetDeviceProperties(&prop, device), "device properties") ||
      !bench::check_cuda(cudaRuntimeGetVersion(&runtime), "runtime version") ||
      !bench::check_cuda(cudaDriverGetVersion(&driver), "driver version")) return 1;

  constexpr std::size_t k = 256;
  bench::Stats stats{};
  if (!run_case(64, 64, k, &stats)) return 1;
  std::printf("{\n  \"gpu\": \"%s\",\n  \"compute_capability\": \"%d.%d\",\n"
              "  \"driver_version\": %d,\n  \"cuda_runtime_version\": %d,\n"
              "  \"kernel\": \"scalar-int8-int32\",\n"
              "  \"M\": 64, \"N\": 64, \"K\": 256,\n"
              "  \"median_ms\": %.6f, \"min_ms\": %.6f, \"p90_ms\": %.6f\n}\n",
              prop.name, prop.major, prop.minor, driver, runtime, stats.median_ms,
              stats.min_ms, stats.p90_ms);
  return 0;
}
