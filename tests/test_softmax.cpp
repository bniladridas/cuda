#include <cmath>
#include <cstddef>
#include <cstdio>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "cuda_kernels/softmax.cuh"
#include "device_status.h"
#include "host_utils.h"

namespace {

const char* const kTest = "softmax";
constexpr float kTolerance = 2.0e-5f;

#define CHECK_CUDA(expr)                                                     \
  do {                                                                       \
    cudaError_t error__ = (expr);                                            \
    host::check(error__ == cudaSuccess, kTest,                               \
                std::string(#expr " failed: ") + cudaGetErrorString(error__)); \
  } while (0)

void run_case(std::size_t rows, std::size_t columns, const std::vector<float>& input,
              const char* label) {
  const std::vector<float> expected = host::softmax_reference(input, rows, columns);
  const std::size_t count = rows * columns;

  float* d_input = nullptr;
  float* d_output = nullptr;
  CHECK_CUDA(cudaMalloc(&d_input, (count == 0 ? 1 : count) * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_output, (count == 0 ? 1 : count) * sizeof(float)));
  if (count != 0) {
    CHECK_CUDA(cudaMemcpy(d_input, input.data(), count * sizeof(float),
                          cudaMemcpyHostToDevice));
  }

  cuda_kernels::launch_softmax(d_input, d_output, rows, columns, nullptr);
  CHECK_CUDA(cudaDeviceSynchronize());

  std::vector<float> got(count);
  if (count != 0) {
    CHECK_CUDA(cudaMemcpy(got.data(), d_output, count * sizeof(float),
                          cudaMemcpyDeviceToHost));
  }
  for (std::size_t row = 0; row < rows; ++row) {
    double sum = 0.0;
    for (std::size_t col = 0; col < columns; ++col) {
      const std::size_t index = row * columns + col;
      host::check(std::isfinite(got[index]), kTest,
                  std::string(label) + ": non-finite output");
      host::check(std::fabs(got[index] - expected[index]) <= kTolerance, kTest,
                  std::string(label) + ": reference mismatch");
      sum += got[index];
    }
    host::check(std::fabs(sum - 1.0) <= 5.0e-5, kTest,
                std::string(label) + ": row sum");
  }

  std::printf("PASS [%s] %s shape=%zux%zu\n", kTest, label, rows, columns);
  CHECK_CUDA(cudaFree(d_input));
  CHECK_CUDA(cudaFree(d_output));
}

void run_stream_case() {
  constexpr std::size_t rows = 3;
  constexpr std::size_t columns = 37;
  const std::vector<float> input =
      host::random_floats(rows * columns, -20.0f, 20.0f, 81u);
  const std::vector<float> expected = host::softmax_reference(input, rows, columns);

  float* d_input = nullptr;
  float* d_output = nullptr;
  cudaStream_t stream = nullptr;
  CHECK_CUDA(cudaStreamCreate(&stream));
  CHECK_CUDA(cudaMalloc(&d_input, input.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&d_output, input.size() * sizeof(float)));
  CHECK_CUDA(cudaMemcpyAsync(d_input, input.data(), input.size() * sizeof(float),
                             cudaMemcpyHostToDevice, stream));

  cuda_kernels::launch_softmax(d_input, d_output, rows, columns,
                               reinterpret_cast<void*>(stream));
  std::vector<float> got(input.size());
  CHECK_CUDA(cudaMemcpyAsync(got.data(), d_output, got.size() * sizeof(float),
                             cudaMemcpyDeviceToHost, stream));
  CHECK_CUDA(cudaStreamSynchronize(stream));

  for (std::size_t i = 0; i < got.size(); ++i) {
    host::check(std::fabs(got[i] - expected[i]) <= kTolerance, kTest,
                "non-default stream mismatch");
  }

  CHECK_CUDA(cudaFree(d_input));
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

  run_case(0, 17, {}, "zero-rows");
  run_case(4, 0, {}, "zero-columns");
  run_case(1, 1, {42.0f}, "single-column");
  run_case(5, 7, std::vector<float>(35, 3.0f), "uniform-irregular");
  run_case(3, 257, host::random_floats(771, -3.0f, 3.0f, 12u), "irregular-257");
  run_case(2, 513, host::random_floats(1026, -100.0f, 100.0f, 13u), "irregular-513");
  run_case(3, 4,
           {1000.0f, 1001.0f, 999.0f, 1002.0f, -1000.0f, -999.0f, -1001.0f,
            -1002.0f, 1.0e-4f, -1.0e-4f, 0.0f, 1.0f},
           "large-and-mixed-magnitudes");
  run_stream_case();

  std::printf("OK [%s] all cases passed\n", kTest);
  return 0;
}
