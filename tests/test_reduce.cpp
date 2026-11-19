#include <cstddef>
#include <cstdio>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "cuda_kernels/reduce.cuh"
#include "device_status.h"
#include "host_utils.h"

namespace {

const char* const kTest = "reduce";

#define CHECK_CUDA(expr)                                                     \
  do {                                                                       \
    cudaError_t err__ = (expr);                                              \
    host::check(err__ == cudaSuccess, kTest,                                 \
                std::string(#expr " failed: ") + cudaGetErrorString(err__)); \
  } while (0)

// Tolerances are relative to max(|ref|, n), a scale that does not collapse when
// the true sum is small relative to the number of terms. A per-thread serial
// accumulation over 1e6 doubles has worst-case error of order n*eps (~2e-10),
// so 1e-9 is a genuine bound rather than a value tuned to pass.
constexpr double kTolFloat = 1e-4;
constexpr double kTolDouble = 1e-9;

template <typename T>
double run_case(const std::vector<T>& x, const char* label, double tol) {
  const std::size_t n = x.size();
  const std::size_t scratch_elems = cuda_kernels::launch_reduce_scratch_elems<T>(n);
  const std::size_t scratch_alloc = scratch_elems == 0 ? 1 : scratch_elems;

  T* d_x = nullptr;
  T* d_out = nullptr;
  T* d_scratch = nullptr;
  CHECK_CUDA(cudaMalloc(&d_x, (n == 0 ? 1 : n) * sizeof(T)));
  CHECK_CUDA(cudaMalloc(&d_out, sizeof(T)));
  CHECK_CUDA(cudaMalloc(&d_scratch, scratch_alloc * sizeof(T)));
  if (n > 0) {
    CHECK_CUDA(cudaMemcpy(d_x, x.data(), n * sizeof(T), cudaMemcpyHostToDevice));
  }

  cuda_kernels::launch_reduce(d_x, d_out, d_scratch, n, nullptr);
  CHECK_CUDA(cudaDeviceSynchronize());

  T got{};
  CHECK_CUDA(cudaMemcpy(&got, d_out, sizeof(T), cudaMemcpyDeviceToHost));
  const double ref = host::sum_reference(x);
  const double err = host::rel_error(ref, static_cast<double>(got), n);

  host::check(err <= tol, kTest,
              std::string("n=") + std::to_string(n) + " (" + label + ") got " +
                  std::to_string(got) + " ref " + std::to_string(ref) + " rel err " +
                  std::to_string(err) + " > tol " + std::to_string(tol));
  std::printf("PASS [%s] n=%zu (%s) sum=%.9g rel_err=%.3g\n", kTest, n, label, ref, err);

  CHECK_CUDA(cudaFree(d_x));
  CHECK_CUDA(cudaFree(d_out));
  CHECK_CUDA(cudaFree(d_scratch));
  return err;
}

template <typename T>
void run_non_default_stream_case(const std::vector<T>& x, const char* label, double tol) {
  const std::size_t n = x.size();
  const std::size_t scratch_elems = cuda_kernels::launch_reduce_scratch_elems<T>(n);
  T* d_x = nullptr;
  T* d_out = nullptr;
  T* d_scratch = nullptr;
  cudaStream_t stream = nullptr;
  CHECK_CUDA(cudaStreamCreate(&stream));
  CHECK_CUDA(cudaMalloc(&d_x, n * sizeof(T)));
  CHECK_CUDA(cudaMalloc(&d_out, sizeof(T)));
  CHECK_CUDA(cudaMalloc(&d_scratch, scratch_elems * sizeof(T)));

  T got{};
  CHECK_CUDA(
      cudaMemcpyAsync(d_x, x.data(), n * sizeof(T), cudaMemcpyHostToDevice, stream));
  cuda_kernels::launch_reduce(d_x, d_out, d_scratch, n, reinterpret_cast<void*>(stream));
  CHECK_CUDA(cudaMemcpyAsync(&got, d_out, sizeof(T), cudaMemcpyDeviceToHost, stream));
  CHECK_CUDA(cudaStreamSynchronize(stream));

  const double ref = host::sum_reference(x);
  const double err = host::rel_error(ref, static_cast<double>(got), n);
  host::check(err <= tol, kTest,
              std::string("non-default stream (") + label + ") got " +
                  std::to_string(got) + " ref " + std::to_string(ref) +
                  " rel err " + std::to_string(err) + " > tol " +
                  std::to_string(tol));
  std::printf("PASS [%s] n=%zu (non-default-stream, %s) rel_err=%.3g\n",
              kTest, n, label, err);

  CHECK_CUDA(cudaStreamDestroy(stream));
  CHECK_CUDA(cudaFree(d_x));
  CHECK_CUDA(cudaFree(d_out));
  CHECK_CUDA(cudaFree(d_scratch));
}

std::vector<float> constant_floats(std::size_t n, float value) {
  return std::vector<float>(n, value);
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

  run_case<float>(constant_floats(0, 1.0f), "empty", kTolFloat);
  run_case<float>(constant_floats(1, 3.5f), "single", kTolFloat);
  run_case<float>(constant_floats(255, 1.0f), "block-1", kTolFloat);
  run_case<float>(constant_floats(256, 1.0f), "block", kTolFloat);
  run_case<float>(constant_floats(257, 1.0f), "block+1", kTolFloat);
  run_case<float>(constant_floats(1000, 0.0f), "all-zero", kTolFloat);
  run_case<float>(constant_floats(1000, 1.0f), "all-one", kTolFloat);
  run_case<float>(host::random_floats(1u << 20, -1.0f, 1.0f, 7u), "random-1Mi",
                  kTolFloat);
  run_case<float>(host::random_floats(1000003, -1.0e6f, 1.0e6f, 9u), "large-magnitude",
                  kTolFloat);

  std::vector<double> d_small = {0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9};
  run_case<double>(d_small, "double-cancellation", kTolDouble);
  std::vector<double> d_big(1000003);
  for (std::size_t i = 0; i < d_big.size(); ++i) {
    d_big[i] = static_cast<double>(i % 1000) * 0.001;
  }
  run_case<double>(d_big, "double-odd-large", kTolDouble);

  run_non_default_stream_case<float>(
      host::random_floats(100003, -1.0f, 1.0f, 41u), "float", kTolFloat);
  std::vector<double> stream_double(100003);
  for (std::size_t i = 0; i < stream_double.size(); ++i) {
    stream_double[i] = static_cast<double>(i % 97) * 0.125;
  }
  run_non_default_stream_case<double>(stream_double, "double", kTolDouble);

  std::printf("OK [%s] all cases passed\n", kTest);
  return 0;
}
