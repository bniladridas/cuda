#include <cstdio>
#include <vector>

#include "device_buffer.h"

namespace {

struct FakeApi {
  int allocations = 0;
  int releases = 0;
  int fail_at = 0;
  int fail_free = 0;
  std::vector<int*> live;

  int success() const { return 0; }

  template <class T>
  int allocate(T** out, std::size_t) {
    ++allocations;
    if (allocations == fail_at) return 1;
    *out = reinterpret_cast<T*>(new int(allocations));
    live.push_back(reinterpret_cast<int*>(*out));
    return 0;
  }

  int release(void* pointer) {
    ++releases;
    auto* value = static_cast<int*>(pointer);
    for (auto it = live.begin(); it != live.end(); ++it) {
      if (*it == value) {
        live.erase(it);
        break;
      }
    }
    delete value;
    return releases == fail_free ? 2 : 0;
  }
};

int failures = 0;

void check(bool ok, const char* message) {
  if (!ok) {
    std::fprintf(stderr, "FAIL [device_buffer] %s\\n", message);
    ++failures;
  }
}

void test_partial_allocation_failure() {
  FakeApi api;
  int reported = 0;
  auto report = [&reported](int, const char*) { ++reported; };
  {
    bench::DeviceBuffer<FakeApi, int, decltype(report)> first(api, report);
    bench::DeviceBuffer<FakeApi, int, decltype(report)> second(api, report);
    bench::DeviceBuffer<FakeApi, int, decltype(report)> third(api, report);
    check(first.allocate(4, "first"), "first allocation failed");
    check(second.allocate(4, "second"), "second allocation failed");
    api.fail_at = 3;
    check(!third.allocate(4, "third"), "injected allocation failure was accepted");
  }
  check(api.releases == 2 && api.live.empty(), "partial allocation leaked a buffer");
  check(reported == 1, "allocation failure was not reported");
}

void test_cleanup_failure() {
  FakeApi api;
  api.fail_free = 1;
  int reported = 0;
  auto report = [&reported](int, const char*) { ++reported; };
  {
    bench::DeviceBuffer<FakeApi, int, decltype(report)> buffer(api, report);
    check(buffer.allocate(4, "buffer"), "allocation failed");
  }
  check(api.releases == 1 && api.live.empty(), "cleanup did not release allocation");
  check(reported == 1, "cleanup failure was not reported");
}

}  // namespace

int main() {
  test_partial_allocation_failure();
  test_cleanup_failure();
  if (failures != 0) return 1;
  std::puts("OK [device_buffer] all allocation lifecycle checks passed");
  return 0;
}
