#pragma once

#include <cstddef>

namespace bench {

// Api supplies Status, Kind, success(), and copy(). The injected API keeps
// CUDA copy failures testable on hosts without a CUDA toolkit or device.
template <typename Api, typename ErrorHandler>
bool checked_memcpy(Api& api, void* destination, const void* source, std::size_t bytes,
                    typename Api::Kind kind, const char* operation,
                    ErrorHandler&& report_error) {
  const auto status = api.copy(destination, source, bytes, kind);
  if (status != api.success()) {
    report_error(status, operation);
    return false;
  }
  return true;
}

}  // namespace bench
