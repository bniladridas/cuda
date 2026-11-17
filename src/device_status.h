#pragma once

namespace cuda_device {

enum class Availability {
  kAvailable,
  kUnavailable,
  kError,
};

// Keep classification independent of the CUDA runtime so every branch can be
// exercised by host-only tests.
template <typename Status>
constexpr Availability classify_device_count(Status status, int device_count,
                                             Status success, Status no_device) {
  if (status == no_device) return Availability::kUnavailable;
  if (status != success) return Availability::kError;
  return device_count > 0 ? Availability::kAvailable : Availability::kUnavailable;
}

}  // namespace cuda_device
