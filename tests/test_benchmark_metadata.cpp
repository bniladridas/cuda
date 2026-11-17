#include <cstdio>
#include <string>

#include "device_metadata.h"

namespace {

int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL [benchmark_metadata] %s\n", message);
    ++failures;
  }
}

void successful_queries_preserve_versions() {
  int runtime = 0;
  int driver = 0;
  std::string error;
  const bool ok = bench_metadata::query_versions(
      0, [](int* value) { *value = 12080; return 0; },
      [](int* value) { *value = 12060; return 0; },
      [](int) { return std::string("unexpected"); }, &runtime, &driver, &error);
  check(ok, "successful version queries failed");
  check(runtime == 12080, "runtime version was not retained");
  check(driver == 12060, "driver version was not retained");
  check(error.empty(), "successful queries produced an error");
  check(bench_metadata::format_version(runtime) == "12.8",
        "runtime version formatting changed");
  check(bench_metadata::format_version(driver) == "12.6",
        "driver version formatting changed");
}

void runtime_failure_stops_before_driver_query() {
  int runtime = -1;
  int driver = -1;
  bool driver_called = false;
  std::string error;
  const bool ok = bench_metadata::query_versions(
      0, [](int*) { return 1; },
      [&driver_called](int*) { driver_called = true; return 0; },
      [](int status) { return "mock error " + std::to_string(status); },
      &runtime, &driver, &error);
  check(!ok, "runtime query failure was accepted");
  check(!driver_called, "driver query ran after runtime query failed");
  check(error.find("cudaRuntimeGetVersion") != std::string::npos,
        "runtime failure omitted API name");
  check(error.find("mock error 1") != std::string::npos,
        "runtime failure omitted CUDA error detail");
  check(runtime == -1 && driver == -1,
        "failed query modified output versions");
}

void driver_failure_is_reported() {
  int runtime = -1;
  int driver = -1;
  std::string error;
  const bool ok = bench_metadata::query_versions(
      0, [](int* value) { *value = 12080; return 0; },
      [](int*) { return 2; },
      [](int status) { return "mock error " + std::to_string(status); },
      &runtime, &driver, &error);
  check(!ok, "driver query failure was accepted");
  check(error.find("cudaDriverGetVersion") != std::string::npos,
        "driver failure omitted API name");
  check(error.find("mock error 2") != std::string::npos,
        "driver failure omitted CUDA error detail");
  check(runtime == -1 && driver == -1,
        "failed query modified output versions");
}

}  // namespace

int main() {
  successful_queries_preserve_versions();
  runtime_failure_stops_before_driver_query();
  driver_failure_is_reported();
  if (failures != 0) {
    std::fprintf(stderr, "benchmark_metadata: %d failure(s)\n", failures);
    return 1;
  }
  std::printf("OK [benchmark_metadata] all metadata query checks passed\n");
  return 0;
}
