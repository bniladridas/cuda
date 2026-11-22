#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <vector>

#include <cuda_runtime.h>

#include "bench.h"
#include "cuda_kernels/attention.cuh"
#include "device_status.h"
#include "attention_reference.h"
#include "host_utils.h"

namespace {
struct Shape {
  std::size_t lq, lk, d, dv;
};

bool run_case(const Shape& s, bench::Stats* stats) {
  const auto q = host::random_floats(s.lq * s.d, -1.0f, 1.0f, 701u);
  const auto k = host::random_floats(s.lk * s.d, -1.0f, 1.0f, 703u);
  const auto v = host::random_floats(s.lk * s.dv, -1.0f, 1.0f, 707u);
  const auto expected = host::attention_reference(q, k, v, s.lq, s.lk, s.d, s.dv);
  const std::size_t scratch_count = s.lq * s.lk;
  float *dq = nullptr, *dk = nullptr, *dvalue = nullptr, *dout = nullptr;
  float *dscores = nullptr, *dprob = nullptr;
  auto cleanup = [&] {
    if (dq) cudaFree(dq);
    if (dk) cudaFree(dk);
    if (dvalue) cudaFree(dvalue);
    if (dout) cudaFree(dout);
    if (dscores) cudaFree(dscores);
    if (dprob) cudaFree(dprob);
  };
  if (!bench::check_cuda(cudaMalloc(&dq, q.size() * sizeof(float)), "alloc Q") ||
      !bench::check_cuda(cudaMalloc(&dk, k.size() * sizeof(float)), "alloc K") ||
      !bench::check_cuda(cudaMalloc(&dvalue, v.size() * sizeof(float)), "alloc V") ||
      !bench::check_cuda(cudaMalloc(&dout, expected.size() * sizeof(float)),
                         "alloc output") ||
      !bench::check_cuda(cudaMalloc(&dscores, scratch_count * sizeof(float)),
                         "alloc scores") ||
      !bench::check_cuda(cudaMalloc(&dprob, scratch_count * sizeof(float)),
                         "alloc probabilities")) {
    cleanup();
    return false;
  }
  bool ok = bench::check_cuda(cudaMemcpy(dq, q.data(), q.size() * sizeof(float),
                                         cudaMemcpyHostToDevice),
                              "copy Q") &&
            bench::check_cuda(cudaMemcpy(dk, k.data(), k.size() * sizeof(float),
                                         cudaMemcpyHostToDevice),
                              "copy K") &&
            bench::check_cuda(cudaMemcpy(dvalue, v.data(), v.size() * sizeof(float),
                                         cudaMemcpyHostToDevice),
                              "copy V");
  if (ok) {
    cuda_kernels::launch_attention_fp32(dq, dk, dvalue, dout, dscores, dprob, s.lq, s.lk,
                                        s.d, s.dv, nullptr);
    ok = bench::check_cuda(cudaDeviceSynchronize(), "attention correctness sync");
  }
  std::vector<float> got(expected.size());
  if (ok) ok = bench::check_cuda(cudaMemcpy(got.data(), dout, got.size() * sizeof(float), cudaMemcpyDeviceToHost), "copy output");
  for (std::size_t i = 0; ok && i < got.size(); ++i) {
    const double scale = std::max(1.0, std::fabs(static_cast<double>(expected[i])));
    ok = std::isfinite(got[i]) && std::fabs(static_cast<double>(got[i]) - expected[i]) <= 8.0e-4 * scale;
  }
  if (ok) ok = bench::measure([&] {
    cuda_kernels::launch_attention_fp32(dq, dk, dvalue, dout, dscores, dprob,
                                        s.lq, s.lk, s.d, s.dv, nullptr);
  }, 100, 7, 20, stats);
  cleanup();
  return ok;
}
}  // namespace

int main() {
  int devices = 0;
  const cudaError_t status = cudaGetDeviceCount(&devices);
  const auto availability = cuda_device::classify_device_count(status, devices, cudaSuccess, cudaErrorNoDevice);
  if (availability == cuda_device::Availability::kUnavailable) {
    std::printf("SKIPPED [attention-benchmark]: no CUDA device\n");
    return 2;
  }
  if (availability == cuda_device::Availability::kError) {
    std::fprintf(stderr, "cudaGetDeviceCount failed: %s\n", cudaGetErrorString(status));
    return 1;
  }
  const Shape shapes[] = {{16, 32, 32, 32}, {64, 96, 64, 48}, {128, 128, 64, 64}};
  bench::Stats results[3];
  for (std::size_t i = 0; i < 3; ++i) {
    if (!run_case(shapes[i], &results[i])) {
      std::fprintf(stderr, "attention correctness or timing failed for case %zu\n", i);
      return 1;
    }
  }
  std::printf("{\n  \"results\": [\n");
  for (std::size_t i = 0; i < 3; ++i) {
    const auto& s = shapes[i];
    const auto& r = results[i];
    std::printf("    {\"Lq\": %zu, \"Lk\": %zu, \"D\": %zu, \"Dv\": %zu, "
                "\"median_ms\": %.6f, \"min_ms\": %.6f, \"p90_ms\": %.6f}%s\n",
                s.lq, s.lk, s.d, s.dv, r.median_ms, r.min_ms, r.p90_ms, i == 2 ? "" : ",");
  }
  std::printf("  ]\n}\n");
  return 0;
}
