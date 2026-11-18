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

#include "event_timer.h"

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

struct CudaEventApi {
  using Event = cudaEvent_t;

  cudaError_t success() const { return cudaSuccess; }
  cudaError_t create(Event* event) { return cudaEventCreate(event); }
  cudaError_t record(Event event) { return cudaEventRecord(event); }
  cudaError_t synchronize(Event event) { return cudaEventSynchronize(event); }
  cudaError_t elapsed(float* ms, Event start, Event stop) {
    return cudaEventElapsedTime(ms, start, stop);
  }
  cudaError_t destroy(Event event) { return cudaEventDestroy(event); }
};

// Runs `work` `iterations` times between two events and returns elapsed
// seconds. `work` must only launch kernels; it must not synchronise. All
// successfully created events are destroyed on every CUDA error path. A cleanup
inline bool time_launches(const std::function<void()>& work, int iterations,
                          double* elapsed_ms) {
  CudaEventApi api;
  return time_launches_with_api(
      api, work, iterations, elapsed_ms,
      [](cudaError_t err, const char* operation) {
        check_cuda(err, operation);
      });
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
  for (double v : per_iter_ms)
    sum += v;
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
