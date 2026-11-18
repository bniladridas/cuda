// Benchmark entry point. Correctness is checked before any timing is reported;
// a kernel that fails its reference comparison exits non-zero without printing
// performance numbers.

#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "bench.h"
#include "checked_copy.h"
#include "device_metadata.h"
#include "device_status.h"
#include "device_buffer.h"
#include "options.h"
#include "cuda_kernels/reduce.cuh"
#include "cuda_kernels/vecadd.cuh"
#include "host_utils.h"

namespace {

struct CudaDeviceMemoryApi {
  using Status = cudaError_t;
  Status success() const { return cudaSuccess; }
  template <typename T>
  Status allocate(T** pointer, std::size_t bytes) {
    return cudaMalloc(reinterpret_cast<void**>(pointer), bytes);
  }
  Status release(void* pointer) { return cudaFree(pointer); }
};

struct CudaMemcpyApi {
  using Status = cudaError_t;
  using Kind = cudaMemcpyKind;

  Status success() const { return cudaSuccess; }
  Status copy(void* destination, const void* source, std::size_t bytes, Kind kind) {
    return cudaMemcpy(destination, source, bytes, kind);
  }
};

bool checked_cuda_memcpy(void* destination, const void* source, std::size_t bytes,
                         cudaMemcpyKind kind, const char* operation) {
  CudaMemcpyApi api;
  return bench::checked_memcpy(
      api, destination, source, bytes, kind, operation,
      [](cudaError_t status, const char* name) { bench::check_cuda(status, name); });
}

void usage(const char* argv0) {
  std::printf("usage: %s [--iterations N] [--reps R] [--warmup W] [--json]\n"
              "\n"
              "  --iterations  launches per timed batch (default %d)\n"
              "  --reps        timed batches to summarise (default %d)\n"
              "  --warmup      untimed launches before measuring (default %d)\n"
              "  limits        iterations/warmup <= 100000, reps <= 1000, "
              "iterations * reps <= 100000\n"
              "  --json        emit machine-readable results instead of a table\n",
              argv0, bench_options::kDefaultIterations, bench_options::kDefaultReps,
              bench_options::kDefaultWarmup);
}

bool device_strings(std::string* name, std::string* capability, std::string* runtime,
                    std::string* driver, std::string* error) {
  int device = 0;
  cudaDeviceProp prop{};
  if (!bench::check_cuda(cudaGetDevice(&device), "cudaGetDevice")) return false;
  if (!bench::check_cuda(cudaGetDeviceProperties(&prop, device),
                         "cudaGetDeviceProperties"))
    return false;

  int runtime_version = 0;
  int driver_version = 0;
  if (!bench_metadata::query_versions(
          cudaSuccess, [](int* version) { return cudaRuntimeGetVersion(version); },
          [](int* version) { return cudaDriverGetVersion(version); },
          [](cudaError_t status) { return std::string(cudaGetErrorString(status)); },
          &runtime_version, &driver_version, error)) {
    return false;
  }

  *name = prop.name;
  *capability = std::to_string(prop.major) + "." + std::to_string(prop.minor);
  *runtime = bench_metadata::format_version(runtime_version);
  *driver = bench_metadata::format_version(driver_version);
  return true;
}

bool vecadd_correct(std::size_t n) {
  const std::vector<float> a = host::random_floats(n, -10.0f, 10.0f, 3u);
  const std::vector<float> b = host::random_floats(n, -10.0f, 10.0f, 4u);
  const std::vector<float> expected = host::vecadd_reference(a, b);

  CudaDeviceMemoryApi memory_api;
  auto report_memory_error = [](cudaError_t status, const char* operation) {
    bench::check_cuda(status, operation);
  };
  bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_a(memory_api, report_memory_error);
  bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_b(memory_api, report_memory_error);
  bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_c(memory_api, report_memory_error);
  if (!d_a.allocate(n * sizeof(float), "cudaMalloc vecadd A")) return false;
  if (!d_b.allocate(n * sizeof(float), "cudaMalloc vecadd B")) return false;
  if (!d_c.allocate(n * sizeof(float), "cudaMalloc vecadd C")) return false;
  if (!checked_cuda_memcpy(d_a.get(), a.data(), n * sizeof(float), cudaMemcpyHostToDevice,
                           "cudaMemcpy vecadd input A (correctness)"))
    return false;
  if (!checked_cuda_memcpy(d_b.get(), b.data(), n * sizeof(float), cudaMemcpyHostToDevice,
                           "cudaMemcpy vecadd input B (correctness)"))
    return false;

  cuda_kernels::launch_vecadd(d_a.get(), d_b.get(), d_c.get(), n, nullptr);
  if (!bench::check_cuda(cudaGetLastError(), "vecadd correctness kernel launch"))
    return false;

  std::vector<float> got(n);
  if (!checked_cuda_memcpy(got.data(), d_c.get(), n * sizeof(float), cudaMemcpyDeviceToHost,
                           "cudaMemcpy vecadd output (correctness)")) {
    return false;
  }
  bool cleanup_ok = d_a.reset();
  cleanup_ok = d_b.reset() && cleanup_ok;
  cleanup_ok = d_c.reset() && cleanup_ok;
  return cleanup_ok && got == expected;
}

bool reduce_correct(std::size_t n) {
  const std::vector<float> x = host::random_floats(n, -1.0f, 1.0f, 5u);
  const std::size_t scratch_elems = cuda_kernels::launch_reduce_scratch_elems<float>(n);

  CudaDeviceMemoryApi memory_api;
  auto report_memory_error = [](cudaError_t status, const char* operation) {
    bench::check_cuda(status, operation);
  };
  bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_x(memory_api, report_memory_error);
  bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_out(memory_api, report_memory_error);
  bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_scratch(memory_api, report_memory_error);
  if (!d_x.allocate(n * sizeof(float), "cudaMalloc reduce input")) return false;
  if (!d_out.allocate(sizeof(float), "cudaMalloc reduce output")) return false;
  if (!d_scratch.allocate(scratch_elems * sizeof(float), "cudaMalloc reduce scratch")) return false;
  if (!checked_cuda_memcpy(d_x.get(), x.data(), n * sizeof(float), cudaMemcpyHostToDevice,
                           "cudaMemcpy reduce input (correctness)"))
    return false;

  cuda_kernels::launch_reduce(d_x.get(), d_out.get(), d_scratch.get(), n, nullptr);
  if (!bench::check_cuda(cudaGetLastError(), "reduce correctness kernel launch"))
    return false;

  float got = 0.0f;
  if (!checked_cuda_memcpy(&got, d_out.get(), sizeof(float), cudaMemcpyDeviceToHost,
                           "cudaMemcpy reduce output (correctness)")) {
    return false;
  }

  bool cleanup_ok = d_x.reset();
  cleanup_ok = d_out.reset() && cleanup_ok;
  cleanup_ok = d_scratch.reset() && cleanup_ok;
  const double ref = host::sum_reference(x);
  return cleanup_ok && host::rel_error(ref, static_cast<double>(got), n) <= 1e-4;
}

struct Row {
  std::string kernel;
  std::size_t n;
  double bytes;
  bench::Stats stats;
};

}  // namespace

int main(int argc, char** argv) {
  bench_options::Options opts;
  std::vector<std::string> arguments;
  arguments.reserve(static_cast<std::size_t>(argc > 1 ? argc - 1 : 0));
  for (int i = 1; i < argc; ++i) {
    arguments.emplace_back(argv[i]);
  }
  std::string parse_error;
  const bench_options::ParseStatus parse_status =
      bench_options::parse_options(arguments, &opts, &parse_error);
  if (parse_status == bench_options::ParseStatus::kHelp) {
    usage(argv[0]);
    return 0;
  }
  if (parse_status == bench_options::ParseStatus::kError) {
    std::fprintf(stderr, "%s\n", parse_error.c_str());
    usage(argv[0]);
    return 2;
  }

  int devices = 0;
  const cudaError_t device_status = cudaGetDeviceCount(&devices);
  const cuda_device::Availability availability = cuda_device::classify_device_count(
      device_status, devices, cudaSuccess, cudaErrorNoDevice);
  if (availability == cuda_device::Availability::kUnavailable) {
    std::printf("SKIPPED [benchmarks]: no CUDA device\n");
    return 0;
  }
  if (availability == cuda_device::Availability::kError) {
    std::fprintf(stderr, "ERROR [benchmarks]: cudaGetDeviceCount failed: %s\n",
                 cudaGetErrorString(device_status));
    return 1;
  }

  const std::vector<std::size_t> sizes = {1u << 16, 1u << 20, 1u << 24};

  // Correctness gate. No timings are collected unless every size matches.
  for (std::size_t n : sizes) {
    if (!vecadd_correct(n)) {
      std::fprintf(stderr, "vecadd incorrect at n=%zu; refusing to benchmark\n", n);
      return 1;
    }
    if (!reduce_correct(n)) {
      std::fprintf(stderr, "reduce incorrect at n=%zu; refusing to benchmark\n", n);
      return 1;
    }
  }

  std::string gpu_name, capability, runtime, driver, metadata_error;
  if (!device_strings(&gpu_name, &capability, &runtime, &driver, &metadata_error)) {
    if (!metadata_error.empty()) {
      std::fprintf(stderr, "could not query benchmark metadata: %s\n",
                   metadata_error.c_str());
    } else {
      std::fprintf(stderr, "could not query device properties\n");
    }
    return 1;
  }

  std::vector<Row> rows;
  for (std::size_t n : sizes) {
    const std::vector<float> a = host::random_floats(n, -1.0f, 1.0f, 3u);
    const std::vector<float> b = host::random_floats(n, -1.0f, 1.0f, 4u);

    CudaDeviceMemoryApi memory_api;
    auto report_memory_error = [](cudaError_t status, const char* operation) {
      bench::check_cuda(status, operation);
    };
    bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_a(memory_api, report_memory_error);
    bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_b(memory_api, report_memory_error);
    bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_c(memory_api, report_memory_error);
    if (!d_a.allocate(n * sizeof(float), "cudaMalloc vecadd A")) return 1;
    if (!d_b.allocate(n * sizeof(float), "cudaMalloc vecadd B")) return 1;
    if (!d_c.allocate(n * sizeof(float), "cudaMalloc vecadd C")) return 1;
    if (!checked_cuda_memcpy(d_a.get(), a.data(), n * sizeof(float), cudaMemcpyHostToDevice,
                             "cudaMemcpy vecadd input A (timed setup)"))
      return 1;
    if (!checked_cuda_memcpy(d_b.get(), b.data(), n * sizeof(float), cudaMemcpyHostToDevice,
                             "cudaMemcpy vecadd input B (timed setup)"))
      return 1;

    Row va{"vecadd", n, 3.0 * static_cast<double>(n) * sizeof(float), {}};
    if (!bench::measure([&] { cuda_kernels::launch_vecadd(d_a.get(), d_b.get(), d_c.get(), n, nullptr); },
                        opts.iterations, opts.reps, opts.warmup, &va.stats)) {
      return 1;
    }
    rows.push_back(va);
    if (!d_a.reset() || !d_b.reset() || !d_c.reset()) return 1;


    const std::size_t scratch_elems = cuda_kernels::launch_reduce_scratch_elems<float>(n);
    bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_x(memory_api, report_memory_error);
    bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_out(memory_api, report_memory_error);
    bench::DeviceBuffer<CudaDeviceMemoryApi, float, decltype(report_memory_error)> d_scratch(memory_api, report_memory_error);
    if (!d_x.allocate(n * sizeof(float), "cudaMalloc reduce input")) return 1;
    if (!d_out.allocate(sizeof(float), "cudaMalloc reduce output")) return 1;
    if (!d_scratch.allocate(scratch_elems * sizeof(float), "cudaMalloc reduce scratch")) return 1;
    if (!checked_cuda_memcpy(d_x.get(), a.data(), n * sizeof(float), cudaMemcpyHostToDevice,
                             "cudaMemcpy reduce input (timed setup)"))
      return 1;

    Row re{"reduce", n, static_cast<double>(n) * sizeof(float), {}};
    if (!bench::measure(
            [&] { cuda_kernels::launch_reduce(d_x.get(), d_out.get(), d_scratch.get(), n, nullptr); },
            opts.iterations, opts.reps, opts.warmup, &re.stats)) {
      return 1;
    }
    rows.push_back(re);
    bool cleanup_ok = d_x.reset();
    cleanup_ok = d_out.reset() && cleanup_ok;
    cleanup_ok = d_scratch.reset() && cleanup_ok;
    if (!cleanup_ok) return 1;
  }

  if (opts.json) {
    std::printf("{\n");
    std::printf("  \"gpu\": \"%s\",\n", gpu_name.c_str());
    std::printf("  \"compute_capability\": \"%s\",\n", capability.c_str());
    std::printf("  \"driver\": \"%s\",\n", driver.c_str());
    std::printf("  \"cuda_runtime\": \"%s\",\n", runtime.c_str());
    std::printf("  \"iterations_per_batch\": %d,\n", opts.iterations);
    std::printf("  \"batches\": %d,\n", opts.reps);
    std::printf("  \"warmup\": %d,\n", opts.warmup);
    std::printf("  \"results\": [\n");
    for (std::size_t i = 0; i < rows.size(); ++i) {
      const Row& r = rows[i];
      const double gbps = r.bytes / (r.stats.median_ms * 1e-3) / 1e9;
      std::printf(
          "    {\"kernel\": \"%s\", \"n\": %zu, \"median_ms\": %.6f, \"min_ms\": %.6f, "
          "\"p90_ms\": %.6f, \"gb_per_s\": %.2f}%s\n",
          r.kernel.c_str(), r.n, r.stats.median_ms, r.stats.min_ms, r.stats.p90_ms, gbps,
          i + 1 == rows.size() ? "" : ",");
    }
    std::printf("  ]\n}\n");
  } else {
    std::printf("gpu=%s sm_%s driver=%s cuda=%s iterations=%d batches=%d warmup=%d\n\n",
                gpu_name.c_str(), capability.c_str(), driver.c_str(), runtime.c_str(),
                opts.iterations, opts.reps, opts.warmup);
    for (const Row& r : rows) {
      bench::print_stats(r.kernel, r.n, r.bytes, r.stats);
    }
    std::printf("\nmedian is the reported figure; min is the best observed batch. See "
                "docs/methodology.md.\n");
  }
  return 0;
}
