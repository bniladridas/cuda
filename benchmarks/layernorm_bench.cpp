#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <vector>

#include <cuda_runtime.h>

#include "bench.h"
#include "cuda_kernels/layernorm.cuh"
#include "device_status.h"
#include "host_utils.h"

namespace {

constexpr float kEpsilon = 1.0e-5f;
constexpr float kTolerance = 3.0e-5f;

struct Shape {
  std::size_t rows;
  std::size_t features;
};

bool run_case(const Shape& shape, bench::Stats* stats) {
  const std::size_t count = shape.rows * shape.features;
  const auto input = host::random_floats(count, -4.0f, 4.0f, 211u);
  const auto gamma = host::random_floats(shape.features, 0.5f, 1.5f, 223u);
  const auto beta = host::random_floats(shape.features, -0.5f, 0.5f, 227u);
  const auto expected =
      host::layernorm_reference(input, gamma, beta, shape.rows, shape.features, kEpsilon);

  float *d_input = nullptr, *d_gamma = nullptr, *d_beta = nullptr, *d_output = nullptr;
  if (!bench::check_cuda(cudaMalloc(&d_input, count * sizeof(float)),
                         "cudaMalloc input") ||
      !bench::check_cuda(cudaMalloc(&d_gamma, gamma.size() * sizeof(float)),
                         "cudaMalloc gamma") ||
      !bench::check_cuda(cudaMalloc(&d_beta, beta.size() * sizeof(float)), "cudaMalloc beta") ||
      !bench::check_cuda(cudaMalloc(&d_output, count * sizeof(float)), "cudaMalloc output")) {
    if (d_input) cudaFree(d_input);
    if (d_gamma) cudaFree(d_gamma);
    if (d_beta) cudaFree(d_beta);
    if (d_output) cudaFree(d_output);
    return false;
  }

  bool ok = bench::check_cuda(cudaMemcpy(d_input, input.data(), count * sizeof(float),
                                         cudaMemcpyHostToDevice),
                              "copy input") &&
            bench::check_cuda(cudaMemcpy(d_gamma, gamma.data(), gamma.size() * sizeof(float),
                                         cudaMemcpyHostToDevice),
                              "copy gamma") &&
            bench::check_cuda(cudaMemcpy(d_beta, beta.data(), beta.size() * sizeof(float),
                                         cudaMemcpyHostToDevice),
                              "copy beta");
  if (ok) {
    cuda_kernels::launch_layernorm_fp32(d_input, d_gamma, d_beta, d_output, shape.rows,
                                        shape.features, kEpsilon, nullptr);
    ok = bench::check_cuda(cudaGetLastError(), "LayerNorm correctness launch") &&
         bench::check_cuda(cudaDeviceSynchronize(), "LayerNorm correctness sync");
  }

  std::vector<float> got(count);
  if (ok) {
    ok = bench::check_cuda(cudaMemcpy(got.data(), d_output, count * sizeof(float),
                                      cudaMemcpyDeviceToHost),
                           "copy output");
  }
  for (std::size_t i = 0; ok && i < count; ++i) {
    const double scale = 1.0 + std::fabs(static_cast<double>(expected[i]));
    ok = std::isfinite(got[i]) &&
         std::fabs(static_cast<double>(got[i]) - expected[i]) <= kTolerance * scale;
  }

  if (ok) {
    ok = bench::measure(
        [&] {
          cuda_kernels::launch_layernorm_fp32(d_input, d_gamma, d_beta, d_output, shape.rows,
                                              shape.features, kEpsilon, nullptr);
        },
        100, 7, 20, stats);
  }

  const bool free_input = bench::check_cuda(cudaFree(d_input), "cudaFree input");
  const bool free_gamma = bench::check_cuda(cudaFree(d_gamma), "cudaFree gamma");
  const bool free_beta = bench::check_cuda(cudaFree(d_beta), "cudaFree beta");
  const bool free_output = bench::check_cuda(cudaFree(d_output), "cudaFree output");
  return ok && free_input && free_gamma && free_beta && free_output;
}

}  // namespace

int main() {
  int devices = 0;
  const cudaError_t status = cudaGetDeviceCount(&devices);
  const auto availability =
      cuda_device::classify_device_count(status, devices, cudaSuccess, cudaErrorNoDevice);
  if (availability == cuda_device::Availability::kUnavailable) {
    std::printf("SKIPPED [layernorm-benchmark]: no CUDA device\n");
    return 2;
  }
  if (availability == cuda_device::Availability::kError) {
    std::fprintf(stderr, "cudaGetDeviceCount failed: %s\n", cudaGetErrorString(status));
    return 1;
  }

  int device = 0, runtime = 0, driver = 0;
  cudaDeviceProp prop{};
  if (!bench::check_cuda(cudaGetDevice(&device), "cudaGetDevice") ||
      !bench::check_cuda(cudaGetDeviceProperties(&prop, device), "cudaGetDeviceProperties") ||
      !bench::check_cuda(cudaRuntimeGetVersion(&runtime), "cudaRuntimeGetVersion") ||
      !bench::check_cuda(cudaDriverGetVersion(&driver), "cudaDriverGetVersion")) {
    return 1;
  }

  const Shape shapes[] = {{64, 128}, {1024, 768}, {256, 4096}};
  bench::Stats results[3];
  for (std::size_t i = 0; i < 3; ++i) {
    if (!run_case(shapes[i], &results[i])) {
      std::fprintf(stderr, "LayerNorm correctness or timing failed for rows=%zu features=%zu\n",
                   shapes[i].rows, shapes[i].features);
      return 1;
    }
  }

  std::printf("{\n  \"gpu\": \"%s\",\n", prop.name);
  std::printf("  \"compute_capability\": \"%d.%d\",\n", prop.major, prop.minor);
  std::printf("  \"driver_version\": %d,\n  \"cuda_runtime_version\": %d,\n",
              driver, runtime);
  std::printf("  \"epsilon\": %.9g,\n  \"block_threads\": 256,\n  \"results\": [\n",
              kEpsilon);
  for (std::size_t i = 0; i < 3; ++i) {
    const auto& shape = shapes[i];
    const auto& result = results[i];
    std::printf("    {\"rows\": %zu, \"features\": %zu, "
                "\"median_ms\": %.6f, \"min_ms\": %.6f, \"p90_ms\": %.6f}%s\n",
                shape.rows, shape.features, result.median_ms, result.min_ms, result.p90_ms,
                i == 2 ? "" : ",");
  }
  std::printf("  ]\n}\n");
  return 0;
}
