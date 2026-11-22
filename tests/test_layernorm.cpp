#include <cmath>
#include <cstddef>
#include <cstdio>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "cuda_kernels/layernorm.cuh"
#include "device_status.h"
#include "host_utils.h"

namespace {

const char* const kTest = "layernorm";
constexpr float kTolerance = 3.0e-5f;

#define CHECK_CUDA(expr)                                                       \
  do {                                                                         \
    cudaError_t error__ = (expr);                                              \
    host::check(error__ == cudaSuccess, kTest,                                 \
                std::string(#expr " failed: ") + cudaGetErrorString(error__)); \
  } while (0)

void run_case(std::size_t rows, std::size_t features, const std::vector<float>& input,
              const std::vector<float>& gamma, const std::vector<float>& beta,
              float epsilon, const char* label) {
  const std::vector<float> expected =
      host::layernorm_reference(input, gamma, beta, rows, features, epsilon);
  const std::size_t count = rows * features;
  float* d_input = nullptr;
  float* d_gamma = nullptr;
  float* d_beta = nullptr;
  float* d_output = nullptr;
  CHECK_CUDA(cudaMalloc(&d_input, (count == 0 ? 1 : count) * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_gamma, (features == 0 ? 1 : features) * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_beta, (features == 0 ? 1 : features) * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_output, (count == 0 ? 1 : count) * sizeof(float)));
  if (count != 0) {
    CHECK_CUDA(cudaMemcpy(d_input, input.data(), count * sizeof(float), cudaMemcpyHostToDevice));
  }
  if (features != 0) {
    CHECK_CUDA(cudaMemcpy(d_gamma, gamma.data(), features * sizeof(float), cudaMemcpyHostToDevice));
    CHECK_CUDA(cudaMemcpy(d_beta, beta.data(), features * sizeof(float), cudaMemcpyHostToDevice));
  }

  cuda_kernels::launch_layernorm_fp32(d_input, d_gamma, d_beta, d_output, rows, features,
                                      epsilon, nullptr);
  CHECK_CUDA(cudaDeviceSynchronize());
  std::vector<float> got(count);
  if (count != 0) {
    CHECK_CUDA(cudaMemcpy(got.data(), d_output, count * sizeof(float), cudaMemcpyDeviceToHost));
  }
  for (std::size_t i = 0; i < count; ++i) {
    host::check(std::isfinite(got[i]), kTest, std::string(label) + ": non-finite output");
    host::check(std::fabs(got[i] - expected[i]) <=
                    kTolerance * (1.0f + std::fabs(expected[i])),
                kTest, std::string(label) + ": CPU reference mismatch");
  }
  std::printf("PASS [%s] %s shape=%zux%zu\n", kTest, label, rows, features);
  CHECK_CUDA(cudaFree(d_input));
  CHECK_CUDA(cudaFree(d_gamma));
  CHECK_CUDA(cudaFree(d_beta));
  CHECK_CUDA(cudaFree(d_output));
}

void run_stream_case() {
  constexpr std::size_t rows = 3;
  constexpr std::size_t features = 37;
  const std::vector<float> input = host::random_floats(rows * features, -5.0f, 5.0f, 71u);
  const std::vector<float> gamma = host::random_floats(features, 0.5f, 1.5f, 72u);
  const std::vector<float> beta = host::random_floats(features, -0.5f, 0.5f, 73u);
  const auto expected = host::layernorm_reference(input, gamma, beta, rows, features, 1.0e-5f);

  float *d_input = nullptr, *d_gamma = nullptr, *d_beta = nullptr, *d_output = nullptr;
  cudaStream_t stream = nullptr;
  CHECK_CUDA(cudaStreamCreate(&stream));
  CHECK_CUDA(cudaMalloc(&d_input, input.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_gamma, gamma.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_beta, beta.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_output, input.size() * sizeof(float)));
  CHECK_CUDA(cudaMemcpyAsync(d_input, input.data(), input.size() * sizeof(float),
                             cudaMemcpyHostToDevice, stream));
  CHECK_CUDA(cudaMemcpyAsync(d_gamma, gamma.data(), gamma.size() * sizeof(float),
                             cudaMemcpyHostToDevice, stream));
  CHECK_CUDA(cudaMemcpyAsync(d_beta, beta.data(), beta.size() * sizeof(float),
                             cudaMemcpyHostToDevice, stream));
  cuda_kernels::launch_layernorm_fp32(d_input, d_gamma, d_beta, d_output, rows, features,
                                      1.0e-5f, reinterpret_cast<void*>(stream));
  std::vector<float> got(input.size());
  CHECK_CUDA(cudaMemcpyAsync(got.data(), d_output, got.size() * sizeof(float),
                             cudaMemcpyDeviceToHost, stream));
  CHECK_CUDA(cudaStreamSynchronize(stream));
  for (std::size_t i = 0; i < got.size(); ++i) {
    host::check(std::fabs(got[i] - expected[i]) <=
                    kTolerance * (1.0f + std::fabs(expected[i])),
                kTest, "non-default stream mismatch");
  }
  CHECK_CUDA(cudaFree(d_input));
  CHECK_CUDA(cudaFree(d_gamma));
  CHECK_CUDA(cudaFree(d_beta));
  CHECK_CUDA(cudaFree(d_output));
  CHECK_CUDA(cudaStreamDestroy(stream));
}

}  // namespace

int main() {
  int devices = 0;
  const cudaError_t status = cudaGetDeviceCount(&devices);
  const cuda_device::Availability availability =
      cuda_device::classify_device_count(status, devices, cudaSuccess, cudaErrorNoDevice);
  if (availability == cuda_device::Availability::kUnavailable) {
    std::printf("SKIPPED [%s]: no CUDA device\n", kTest);
    return 0;
  }
  if (availability == cuda_device::Availability::kError) {
    std::fprintf(stderr, "ERROR [%s]: %s\n", kTest, cudaGetErrorString(status));
    return 1;
  }

  run_case(0, 17, {}, std::vector<float>(17, 1.0f), std::vector<float>(17, 0.0f),
           1.0e-5f, "zero-rows");
  run_case(3, 0, {}, {}, {}, 1.0e-5f, "zero-features");
  run_case(1, 1, {4.0f}, {2.0f}, {-1.0f}, 1.0e-5f, "single-feature");
  run_case(4, 7, std::vector<float>(28, 3.0f), std::vector<float>(7, 1.0f),
           std::vector<float>(7, 0.0f), 1.0e-5f, "constant-rows");
  run_case(3, 257, host::random_floats(771, -3.0f, 3.0f, 14u),
           host::random_floats(257, 0.5f, 1.5f, 15u),
           host::random_floats(257, -0.5f, 0.5f, 16u), 1.0e-5f, "irregular-257");
  run_case(2, 513, host::random_floats(1026, -1.0e4f, 1.0e4f, 17u),
           std::vector<float>(513, 1.0f), std::vector<float>(513, 0.0f),
           1.0e-5f, "large-magnitude-513");
  run_stream_case();

  std::printf("OK [%s] all cases passed\n", kTest);
  return 0;
}
