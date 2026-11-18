#include <cstdio>
#include <string>
#include <vector>

#include "checked_copy.h"

namespace {

struct FakeMemcpyApi {
  using Status = int;
  using Kind = int;
  static constexpr Status kSuccess = 0;

  Status result = kSuccess;
  int calls = 0;
  std::vector<std::pair<Status, std::string>> errors;

  Status success() const { return kSuccess; }
  Status copy(void*, const void*, std::size_t, Kind) {
    ++calls;
    return result;
  }
  void report(Status status, const char* operation) {
    errors.emplace_back(status, operation);
  }
};

int failures = 0;
void check(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL [benchmark_checked_copy] %s\n", message);
    ++failures;
  }
}

void test_success() {
  FakeMemcpyApi api;
  int source = 1;
  int destination = 0;
  const bool ok = bench::checked_memcpy(
      api, &destination, &source, sizeof(source), 7, "test copy",
      [&api](int status, const char* operation) { api.report(status, operation); });
  check(ok, "successful copy reported failure");
  check(api.calls == 1, "successful copy was not invoked exactly once");
  check(api.errors.empty(), "successful copy emitted an error");
}

void test_failure_reports_operation() {
  FakeMemcpyApi api;
  api.result = 9;
  int source = 1;
  int destination = 0;
  const bool ok = bench::checked_memcpy(
      api, &destination, &source, sizeof(source), 7, "cudaMemcpy input setup",
      [&api](int status, const char* operation) { api.report(status, operation); });
  check(!ok, "failed copy was accepted");
  check(api.calls == 1, "failed copy was not invoked exactly once");
  check(api.errors.size() == 1, "failed copy did not report exactly one error");
  check(api.errors[0].first == 9, "copy error status was not preserved");
  check(api.errors[0].second == "cudaMemcpy input setup",
        "copy operation context was not preserved");
}

}  // namespace

int main() {
  test_success();
  test_failure_reports_operation();
  if (failures != 0) {
    std::fprintf(stderr, "benchmark_checked_copy: %d failure(s)\n", failures);
    return 1;
  }
  std::printf("OK [benchmark_checked_copy] all copy checks passed\n");
  return 0;
}
