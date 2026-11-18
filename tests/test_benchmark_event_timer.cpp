#include <cstdio>
#include <string>
#include <utility>
#include <vector>

#include "event_timer.h"

namespace {

struct FakeCudaEvents {
  using Event = int;
  using Status = int;
  static constexpr Status kSuccess = 0;

  Status fail_create_at = 0;
  Status fail_record_at = 0;
  Status fail_synchronize = 0;
  Status fail_elapsed = 0;
  Status fail_destroy_at = 0;
  int creates = 0;
  int records = 0;
  int destroys = 0;
  int synchronizes = 0;
  int elapsed_calls = 0;
  std::vector<std::pair<int, std::string>> errors;

  Status success() const { return kSuccess; }
  Status create(Event* event) {
    ++creates;
    *event = creates;
    return creates == fail_create_at ? 1 : kSuccess;
  }
  Status record(Event) {
    ++records;
    return records == fail_record_at ? 2 : kSuccess;
  }
  Status synchronize(Event) {
    ++synchronizes;
    return fail_synchronize ? 3 : kSuccess;
  }
  Status elapsed(float* ms, Event, Event) {
    ++elapsed_calls;
    *ms = 12.5f;
    return fail_elapsed ? 4 : kSuccess;
  }
  Status destroy(Event) {
    ++destroys;
    return destroys == fail_destroy_at ? 5 : kSuccess;
  }
  void report(Status status, const char* operation) {
    errors.emplace_back(status, operation);
  }
};

int failures = 0;
void check(bool condition, const std::string& message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL [benchmark_event_timer] %s\n", message.c_str());
    ++failures;
  }
}

template <typename Configure>
void failure_case(const char* name, Configure configure, int expected_creates,
                  int expected_destroys, int expected_error) {
  FakeCudaEvents api;
  configure(api);
  double elapsed = -1.0;
  const bool ok = bench::time_launches_with_api(
      api, [] {}, 3, &elapsed,
      [&api](int status, const char* operation) { api.report(status, operation); });
  check(!ok, std::string(name) + ": failure accepted");
  check(api.creates == expected_creates, std::string(name) + ": unexpected creates");
  check(api.destroys == expected_destroys,
        std::string(name) + ": leaked or over-destroyed events");
  check(!api.errors.empty() && api.errors.front().first == expected_error,
        std::string(name) + ": primary error not reported first");
  check(elapsed == -1.0, std::string(name) + ": wrote elapsed time on failure");
}

void test_create_failures() {
  failure_case("first create", [](FakeCudaEvents& api) { api.fail_create_at = 1; },
               1, 0, 1);
  failure_case("second create", [](FakeCudaEvents& api) { api.fail_create_at = 2; },
               2, 1, 1);
}

void test_record_and_completion_failures() {
  failure_case("start record", [](FakeCudaEvents& api) { api.fail_record_at = 1; },
               2, 2, 2);
  failure_case("stop record", [](FakeCudaEvents& api) { api.fail_record_at = 2; },
               2, 2, 2);
  failure_case("synchronize", [](FakeCudaEvents& api) { api.fail_synchronize = 1; },
               2, 2, 3);
  failure_case("elapsed", [](FakeCudaEvents& api) { api.fail_elapsed = 1; },
               2, 2, 4);
}

void test_success_and_cleanup_failure() {
  FakeCudaEvents api;
  double elapsed = -1.0;
  const bool ok = bench::time_launches_with_api(
      api, [] {}, 3, &elapsed,
      [&api](int status, const char* operation) { api.report(status, operation); });
  check(ok, "successful timing failed");
  check(api.creates == 2 && api.destroys == 2,
        "success did not destroy both events");
  check(api.records == 2 && api.synchronizes == 1 && api.elapsed_calls == 1,
        "success did not execute all timing operations");
  check(elapsed == 12.5, "success did not publish elapsed time");

  FakeCudaEvents cleanup_api;
  cleanup_api.fail_destroy_at = 1;
  elapsed = -1.0;
  const bool cleanup_ok = bench::time_launches_with_api(
      cleanup_api, [] {}, 3, &elapsed,
      [&cleanup_api](int status, const char* operation) {
        cleanup_api.report(status, operation);
      });
  check(!cleanup_ok, "cleanup failure was accepted");
  check(cleanup_api.destroys == 2,
        "cleanup failure prevented second destroy");
  check(cleanup_api.errors.size() == 1 &&
            cleanup_api.errors.front().second == "cudaEventDestroy",
        "cleanup failure was not reported");
  check(elapsed == -1.0, "published elapsed time after cleanup failure");
}

void test_primary_error_survives_cleanup_failure() {
  FakeCudaEvents api;
  api.fail_record_at = 1;
  api.fail_destroy_at = 1;
  double elapsed = -1.0;
  const bool ok = bench::time_launches_with_api(
      api, [] {}, 3, &elapsed,
      [&api](int status, const char* operation) { api.report(status, operation); });
  check(!ok, "primary failure was accepted");
  check(api.errors.size() == 2,
        "primary and cleanup failures were not both reported");
  check(api.errors[0].first == 2 && api.errors[0].second == "cudaEventRecord",
        "cleanup failure replaced primary error");
  check(api.errors[1].first == 5 && api.errors[1].second == "cudaEventDestroy",
        "cleanup error was not reported after primary error");
  check(api.destroys == 2,
        "second event was not destroyed after first destroy failed");
}

}  // namespace

int main() {
  test_create_failures();
  test_record_and_completion_failures();
  test_success_and_cleanup_failure();
  test_primary_error_survives_cleanup_failure();
  if (failures != 0) {
    std::fprintf(stderr, "benchmark_event_timer: %d failure(s)\n", failures);
    return 1;
  }
  std::printf("OK [benchmark_event_timer] all event lifecycle checks passed\n");
  return 0;
}
