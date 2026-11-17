#include <cstdio>
#include <cstdlib>

#include "device_status.h"

namespace {

enum class FakeCudaError {
  kSuccess,
  kNoDevice,
  kInsufficientDriver,
  kInitializationFailure,
};

void expect(cuda_device::Availability actual, cuda_device::Availability expected,
            const char* label) {
  if (actual != expected) {
    std::fprintf(stderr, "FAIL [device_status]: %s\n", label);
    std::exit(1);
  }
}

}  // namespace

int main() {
  using cuda_device::Availability;
  using Fake = FakeCudaError;

  expect(cuda_device::classify_device_count(Fake::kSuccess, 1, Fake::kSuccess,
                                            Fake::kNoDevice),
         Availability::kAvailable, "successful query with a device");
  expect(cuda_device::classify_device_count(Fake::kSuccess, 0, Fake::kSuccess,
                                            Fake::kNoDevice),
         Availability::kUnavailable, "successful query with zero devices");
  expect(cuda_device::classify_device_count(Fake::kNoDevice, 0, Fake::kSuccess,
                                            Fake::kNoDevice),
         Availability::kUnavailable, "explicit no-device result");
  expect(cuda_device::classify_device_count(Fake::kInsufficientDriver, 0, Fake::kSuccess,
                                            Fake::kNoDevice),
         Availability::kError, "insufficient driver is an error");
  expect(cuda_device::classify_device_count(Fake::kInitializationFailure, 0,
                                            Fake::kSuccess, Fake::kNoDevice),
         Availability::kError, "initialization failure is an error");

  std::puts("OK [device_status] all cases passed");
  return 0;
}
