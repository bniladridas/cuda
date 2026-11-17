#pragma once

#include <string>

namespace bench_metadata {

// Query callbacks return the platform status type and write the version only
// on success. Keeping the callbacks injectable lets the failure paths run in
// host-only tests without a CUDA toolkit.
template <typename Status, typename RuntimeQuery, typename DriverQuery,
          typename ErrorString>
bool query_versions(Status success, RuntimeQuery runtime_query,
                    DriverQuery driver_query, ErrorString error_string,
                    int* runtime_version, int* driver_version,
                    std::string* error) {
  int runtime = 0;
  const Status runtime_status = runtime_query(&runtime);
  if (runtime_status != success) {
    *error = "cudaRuntimeGetVersion: " + error_string(runtime_status);
    return false;
  }

  int driver = 0;
  const Status driver_status = driver_query(&driver);
  if (driver_status != success) {
    *error = "cudaDriverGetVersion: " + error_string(driver_status);
    return false;
  }

  *runtime_version = runtime;
  *driver_version = driver;
  return true;
}

inline std::string format_version(int version) {
  return std::to_string(version / 1000) + "." +
         std::to_string((version % 1000) / 10);
}

}  // namespace bench_metadata
