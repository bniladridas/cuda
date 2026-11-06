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
#include "cuda_kernels/reduce.cuh"
#include "cuda_kernels/vecadd.cuh"
#include "host_utils.h"

namespace {

constexpr int kDefaultIterations = 200;
constexpr int kDefaultReps = 7;
constexpr int kDefaultWarmup = 20;

struct Options {
  int iterations = kDefaultIterations;
  int reps = kDefaultReps;
  int warmup = kDefaultWarmup;
  bool json = false;
};

void usage(const char* argv0) {
  std::printf(
      "usage: %s [--iterations N] [--reps R] [--warmup W] [--json]\n"
      "\n"
      "  --iterations  launches per timed batch (default %d)\n"
      "  --reps        timed batches to summarise (default %d)\n"
      "  --warmup      untimed launches before measuring (default %d)\n"
      "  --json        emit machine-readable results instead of a table\n",
      argv0, kDefaultIterations, kDefaultReps, kDefaultWarmup);
}

bool parse_options(int argc, char** argv, Options* opts) {
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto next = [&](int* dst) {
      if (i + 1 >= argc) return false;
      *dst = std::atoi(argv[++i]);
      return *dst > 0;
    };
    if (arg == "--help" || arg == "-h") {
      usage(argv[0]);
      std::exit(0);
    } else if (arg == "--json") {
      opts->json = true;
    } else if (arg == "--iterations") {
      if (!next(&opts->iterations)) return false;
    } else if (arg == "--reps") {
      if (!next(&opts->reps)) return false;
    } else if (arg == "--warmup") {
      if (!next(&opts->warmup)) return false;
    } else {
      std::fprintf(stderr, "unknown argument: %s\n", arg.c_str());
      return false;
    }
  }
  return true;
}

bool device_strings(std::string* name, std::string* capability, std::string* driver) {
  int device = 0;
  cudaDeviceProp prop{};
  if (cudaGetDevice(&device) != cudaSuccess) return false;
  if (cudaGetDeviceProperties(&prop, device) != cudaSuccess) return false;
  int rt = 0;
  int drv = 0;
  cudaRuntimeGetVersion(&rt);
  cudaDriverGetVersion(&drv);
  *name = prop.name;
  *capability = std::to_string(prop.major) + "." + std::to_string(prop.minor);
  *driver = std::to_string(drv / 1000) + "." + std::to_string((drv % 1000) / 10);
  return true;
}

bool vecadd_correct(std::size_t n) {
  const std::vector<float> a = host::random_floats(n, -10.0f, 10.0f, 3u);
  const std::vector<float> b = host::random_floats(n, -10.0f, 10.0f, 4u);
  const std::vector<float> expected = host::vecadd_reference(a, b);

  float* d_a = nullptr;
  float* d_b = nullptr;
  float* d_c = nullptr;
  if (!bench::check_cuda(cudaMalloc(&d_a, n * sizeof(float)), "cudaMalloc")) return false;
  if (!bench::check_cuda(cudaMalloc(&d_b, n * sizeof(float)), "cudaMalloc")) return false;
  if (!bench::check_cuda(cudaMalloc(&d_c, n * sizeof(float)), "cudaMalloc")) return false;
  cudaMemcpy(d_a, a.data(), n * sizeof(float), cudaMemcpyHostToDevice);
  cudaMemcpy(d_b, b.data(), n * sizeof(float), cudaMemcpyHostToDevice);

  cuda_kernels::launch_vecadd(d_a, d_b, d_c, n, nullptr);

  std::vector<float> got(n);
  if (!bench::check_cuda(cudaMemcpy(got.data(), d_c, n * sizeof(float),
                                    cudaMemcpyDeviceToHost),
                         "cudaMemcpy")) {
    return false;
  }
  cudaFree(d_a);
  cudaFree(d_b);
  cudaFree(d_c);
  return got == expected;
}

bool reduce_correct(std::size_t n) {
  const std::vector<float> x = host::random_floats(n, -1.0f, 1.0f, 5u);
  const std::size_t scratch_elems = cuda_kernels::launch_reduce_scratch_elems<float>(n);

  float* d_x = nullptr;
  float* d_out = nullptr;
  float* d_scratch = nullptr;
  if (!bench::check_cuda(cudaMalloc(&d_x, n * sizeof(float)), "cudaMalloc")) return false;
  if (!bench::check_cuda(cudaMalloc(&d_out, sizeof(float)), "cudaMalloc")) return false;
  if (!bench::check_cuda(cudaMalloc(&d_scratch, scratch_elems * sizeof(float)),
                         "cudaMalloc")) {
    return false;
  }
  cudaMemcpy(d_x, x.data(), n * sizeof(float), cudaMemcpyHostToDevice);

  cuda_kernels::launch_reduce(d_x, d_out, d_scratch, n, nullptr);

  float got = 0.0f;
  if (!bench::check_cuda(cudaMemcpy(&got, d_out, sizeof(float), cudaMemcpyDeviceToHost),
                         "cudaMemcpy")) {
    return false;
  }
  cudaFree(d_x);
  cudaFree(d_out);
  cudaFree(d_scratch);

  const double ref = host::sum_reference(x);
  return host::rel_error(ref, static_cast<double>(got), n) <= 1e-4;
}

struct Row {
  std::string kernel;
  std::size_t n;
  double bytes;
  bench::Stats stats;
};

}  // namespace

int main(int argc, char** argv) {
  Options opts;
  if (!parse_options(argc, argv, &opts)) {
    usage(argv[0]);
    return 2;
  }

  int devices = 0;
  if (cudaGetDeviceCount(&devices) != cudaSuccess || devices == 0) {
    std::printf("SKIPPED [benchmarks]: no CUDA device\n");
    return 0;
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

  std::string gpu_name, capability, driver;
  if (!device_strings(&gpu_name, &capability, &driver)) {
    std::fprintf(stderr, "could not query device properties\n");
    return 1;
  }

  std::vector<Row> rows;
  for (std::size_t n : sizes) {
    const std::vector<float> a = host::random_floats(n, -1.0f, 1.0f, 3u);
    const std::vector<float> b = host::random_floats(n, -1.0f, 1.0f, 4u);

    float* d_a = nullptr;
    float* d_b = nullptr;
    float* d_c = nullptr;
    if (!bench::check_cuda(cudaMalloc(&d_a, n * sizeof(float)), "cudaMalloc")) return 1;
    if (!bench::check_cuda(cudaMalloc(&d_b, n * sizeof(float)), "cudaMalloc")) return 1;
    if (!bench::check_cuda(cudaMalloc(&d_c, n * sizeof(float)), "cudaMalloc")) return 1;
    cudaMemcpy(d_a, a.data(), n * sizeof(float), cudaMemcpyHostToDevice);
    cudaMemcpy(d_b, b.data(), n * sizeof(float), cudaMemcpyHostToDevice);

    Row va{"vecadd", n, 3.0 * static_cast<double>(n) * sizeof(float), {}};
    if (!bench::measure([&] { cuda_kernels::launch_vecadd(d_a, d_b, d_c, n, nullptr); },
                        opts.iterations, opts.reps, opts.warmup, &va.stats)) {
      return 1;
    }
    rows.push_back(va);

    cudaFree(d_a);
    cudaFree(d_b);
    cudaFree(d_c);

    const std::size_t scratch_elems = cuda_kernels::launch_reduce_scratch_elems<float>(n);
    float* d_x = nullptr;
    float* d_out = nullptr;
    float* d_scratch = nullptr;
    if (!bench::check_cuda(cudaMalloc(&d_x, n * sizeof(float)), "cudaMalloc")) return 1;
    if (!bench::check_cuda(cudaMalloc(&d_out, sizeof(float)), "cudaMalloc")) return 1;
    if (!bench::check_cuda(cudaMalloc(&d_scratch, scratch_elems * sizeof(float)),
                           "cudaMalloc")) {
      return 1;
    }
    cudaMemcpy(d_x, a.data(), n * sizeof(float), cudaMemcpyHostToDevice);

    Row re{"reduce", n, static_cast<double>(n) * sizeof(float), {}};
    if (!bench::measure(
            [&] { cuda_kernels::launch_reduce(d_x, d_out, d_scratch, n, nullptr); },
            opts.iterations, opts.reps, opts.warmup, &re.stats)) {
      return 1;
    }
    rows.push_back(re);

    cudaFree(d_x);
    cudaFree(d_out);
    cudaFree(d_scratch);
  }

  const std::string cuda_ver = std::to_string(CUDART_VERSION / 1000) + "." +
                               std::to_string((CUDART_VERSION % 1000) / 10);

  if (opts.json) {
    std::printf("{\n");
    std::printf("  \"gpu\": \"%s\",\n", gpu_name.c_str());
    std::printf("  \"compute_capability\": \"%s\",\n", capability.c_str());
    std::printf("  \"driver\": \"%s\",\n", driver.c_str());
    std::printf("  \"cuda_runtime\": \"%s\",\n", cuda_ver.c_str());
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
                gpu_name.c_str(), capability.c_str(), driver.c_str(), cuda_ver.c_str(),
                opts.iterations, opts.reps, opts.warmup);
    for (const Row& r : rows) {
      bench::print_stats(r.kernel, r.n, r.bytes, r.stats);
    }
    std::printf(
        "\nmedian is the reported figure; min is the best observed batch. See "
        "docs/methodology.md.\n");
  }
  return 0;
}
