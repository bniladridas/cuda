#pragma once

// Timing harness. GPU timings use CUDA events so the measurement excludes host
// launch overhead for the *interval* being reported; the reported figure is
// still end-to-end launch-to-completion, which is what a caller sees.

#include <algorithm>
#include <cstddef>
#include <cstdio>
#include <functional>
#include <string>
#include <vector>

#include <cuda_runtime.h>

namespace bench {

struct Stats {
  double min_ms = 0.0;
  double median_ms = 0.0;
  double mean_ms = 0.0;
  double p90_ms = 0.0;
  int iterations = 0;
};

inline double median(std::vector<double> v) {
  std::sort(v.begin(), v.end());
  const std::size_t mid = v.size() / 2;
  return v.size() % 2 == 0 ? 0.5 * (v[mid - 1] + v[mid]) : v[mid];
}

inline double percentile(std::vector<double> v, double p) {
  std::sort(v.begin(), v.end());
  if (v.empty()) {
    return 0.0;
  }
  const std::size_t idx = static_cast<std::size_t>(p * static_cast<double>(v.size() - 1));
  return v[idx];
}

inline bool check_cuda(cudaError_t err, const char* what) {
  if (err != cudaSuccess) {
    std::fprintf(stderr, "CUDA error in %s: %s\n", what, cudaGetErrorString(err));
    return false;
  }
  return true;
}

// Runs `work` `iterations` times between two events and returns elapsed
// seconds. `work` must only launch kernels; it must not synchronise.
inline bool time_launches(const std::function<void()>& work, int iterations,
                          double* elapsed_ms) {
  cudaEvent_t start = nullptr;
  cudaEvent_t stop = nullptr;
  if (!check_cuda(cudaEventCreate(&start), "cudaEventCreate")) return false;
  if (!check_cuda(cudaEventCreate(&stop), "cudaEventCreate")) return false;

  if (!check_cuda(cudaEventRecord(start), "cudaEventRecord")) return false;
  for (int i = 0; i < iterations; ++i) {
    work();
  }
  if (!check_cuda(cudaEventRecord(stop), "cudaEventRecord")) return false;
  if (!check_cuda(cudaEventSynchronize(stop), "cudaEventSynchronize")) return false;

  float ms = 0.0f;
  if (!check_cuda(cudaEventElapsedTime(&ms, start, stop), "cudaEventElapsedTime")) {
    return false;
  }
  *elapsed_ms = static_cast<double>(ms);
  cudaEventDestroy(start);
  cudaEventDestroy(stop);
  return true;
}

// Repeats a timed batch `reps` times and summarises per-iteration times.
// A warmup batch is run first and discarded, so first-touch page faults and
// one-off clock ramp-up do not land in the reported samples.
inline bool measure(const std::function<void()>& work, int iterations, int reps,
                    int warmup_iterations, Stats* out) {
  double ignored = 0.0;
  if (!time_launches(work, warmup_iterations, &ignored)) {
    return false;
  }

  std::vector<double> per_iter_ms;
  per_iter_ms.reserve(static_cast<std::size_t>(reps));
  for (int r = 0; r < reps; ++r) {
    double total_ms = 0.0;
    if (!time_launches(work, iterations, &total_ms)) {
      return false;
    }
    per_iter_ms.push_back(total_ms / static_cast<double>(iterations));
  }

  out->iterations = iterations * reps;
  out->min_ms = *std::min_element(per_iter_ms.begin(), per_iter_ms.end());
  out->median_ms = median(per_iter_ms);
  out->p90_ms = percentile(per_iter_ms, 0.90);
  double sum = 0.0;
  for (double v : per_iter_ms) sum += v;
  out->mean_ms = sum / static_cast<double>(per_iter_ms.size());
  return true;
}

inline void print_stats(const std::string& name, std::size_t n, double bytes_per_call,
                        const Stats& s) {
  const double gbps = bytes_per_call / (s.median_ms * 1e-3) / 1e9;
  std::printf("%-22s n=%-9zu median=%9.4f ms  min=%9.4f  p90=%9.4f  %8.2f GB/s\n",
              name.c_str(), n, s.median_ms, s.min_ms, s.p90_ms, gbps);
}

}  // namespace bench
