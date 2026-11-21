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
#define CHECK_CUDA(expr) do { cudaError_t e__ = (expr); host::check(e__ == cudaSuccess, kTest, std::string(#expr " failed: ") + cudaGetErrorString(e__)); } while (0)
void run_case(std::size_t rows, std::size_t cols, const std::vector<float>& input,
              const char* label) {
  const auto expected = host::softmax_reference(input, rows, cols);
  const std::size_t count = rows * cols;
  float *di = nullptr, *dout = nullptr;
  CHECK_CUDA(cudaMalloc(&di, (count ? count : 1) * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&dout, (count ? count : 1) * sizeof(float)));
  if (count) CHECK_CUDA(cudaMemcpy(di, input.data(), count * sizeof(float), cudaMemcpyHostToDevice));
  cuda_kernels::launch_softmax(di, dout, rows, cols, nullptr);
  CHECK_CUDA(cudaDeviceSynchronize());
  std::vector<float> got(count);
  if (count) CHECK_CUDA(cudaMemcpy(got.data(), dout, count * sizeof(float), cudaMemcpyDeviceToHost));
  for (std::size_t row = 0; row < rows; ++row) {
    double sum = 0.0;
    for (std::size_t col = 0; col < cols; ++col) {
      const auto i = row * cols + col;
      host::check(std::isfinite(got[i]), kTest, std::string(label) + ": non-finite output");
      host::check(std::fabs(got[i] - expected[i]) <= kTolerance, kTest,
                  std::string(label) + ": reference mismatch");
      sum += got[i];
    }
    host::check(std::fabs(sum - 1.0) <= 5.0e-5, kTest, std::string(label) + ": row sum");
  }
  std::printf("PASS [%s] %s shape=%zux%zu\n", kTest, label, rows, cols);
  CHECK_CUDA(cudaFree(di)); CHECK_CUDA(cudaFree(dout));
}
void run_stream_case() {
  constexpr std::size_t rows = 3, cols = 37;
  const auto input = host::random_floats(rows * cols, -20.0f, 20.0f, 81u);
  const auto expected = host::softmax_reference(input, rows, cols);
  float *di = nullptr, *dout = nullptr; cudaStream_t stream = nullptr;
  CHECK_CUDA(cudaStreamCreate(&stream));
  CHECK_CUDA(cudaMalloc(&di, input.size() * sizeof(float)));
  CHECK_CUDA(cudaMalloc(&dout, input.size() * sizeof(float)));
  CHECK_CUDA(cudaMemcpyAsync(di, input.data(), input.size() * sizeof(float), cudaMemcpyHostToDevice, stream));
  cuda_kernels::launch_softmax(di, dout, rows, cols, reinterpret_cast<void*>(stream));
  std::vector<float> got(input.size());
  CHECK_CUDA(cudaMemcpyAsync(got.data(), dout, got.size() * sizeof(float), cudaMemcpyDeviceToHost, stream));
  CHECK_CUDA(cudaStreamSynchronize(stream));
  for (std::size_t i = 0; i < got.size(); ++i)
    host::check(std::fabs(got[i] - expected[i]) <= kTolerance, kTest, "stream mismatch");
  CHECK_CUDA(cudaFree(di)); CHECK_CUDA(cudaFree(dout)); CHECK_CUDA(cudaStreamDestroy(stream));
}
}
int main() {
  int devices = 0;
  const cudaError_t status = cudaGetDeviceCount(&devices);
  const auto availability = cuda_device::classify_device_count(status, devices, cudaSuccess, cudaErrorNoDevice);
  if (availability == cuda_device::Availability::kUnavailable) {
    std::printf("SKIPPED [%s]: no CUDA device\n", kTest); return 0;
  }
  if (availability == cuda_device::Availability::kError) {
    std::fprintf(stderr, "ERROR [%s]: %s\n", kTest, cudaGetErrorString(status)); return 1;
  }
  run_case(0, 17, {}, "zero-rows");
  run_case(4, 0, {}, "zero-columns");
  run_case(1, 1, {42.0f}, "single-column");
  run_case(5, 7, std::vector<float>(35, 3.0f), "uniform-irregular");
  run_case(3, 257, host::random_floats(771, -3.0f, 3.0f, 12u), "irregular-257");
  run_case(2, 513, host::random_floats(1026, -100.0f, 100.0f, 13u), "irregular-513");
  run_case(3, 4, {1000.0f, 1001.0f, 999.0f, 1002.0f, -1000.0f, -999.0f,
                  -1001.0f, -1002.0f, 1.0e-4f, -1.0e-4f, 0.0f, 1.0f},
           "large-and-mixed-magnitudes");
  run_stream_case();
  std::printf("OK [%s] all cases passed\n", kTest); return 0;
}
