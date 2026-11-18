#pragma once

namespace bench {

// Api supplies Event, success(), create(), record(), synchronize(), elapsed(),
// and destroy(). Keeping the operation table generic lets host tests inject
// every CUDA failure without requiring a CUDA toolkit or device.
template <typename Api, typename Work, typename ErrorHandler>
bool time_launches_with_api(Api& api, Work&& work, int iterations,
                            double* elapsed_ms, ErrorHandler&& report_error) {
  using Event = typename Api::Event;

  Event start{};
  Event stop{};
  bool start_created = false;
  bool stop_created = false;

  const auto cleanup = [&]() {
    bool cleanup_ok = true;
    if (stop_created) {
      const auto status = api.destroy(stop);
      stop_created = false;
      if (status != api.success()) {
        report_error(status, "cudaEventDestroy");
        cleanup_ok = false;
      }
    }
    if (start_created) {
      const auto status = api.destroy(start);
      start_created = false;
      if (status != api.success()) {
        report_error(status, "cudaEventDestroy");
        cleanup_ok = false;
      }
    }
    return cleanup_ok;
  };

  const auto fail = [&](auto status, const char* operation) {
    report_error(status, operation);
    cleanup();
    return false;
  };

  auto status = api.create(&start);
  if (status != api.success()) return fail(status, "cudaEventCreate");
  start_created = true;

  status = api.create(&stop);
  if (status != api.success()) return fail(status, "cudaEventCreate");
  stop_created = true;

  status = api.record(start);
  if (status != api.success()) return fail(status, "cudaEventRecord");
  for (int i = 0; i < iterations; ++i) work();

  status = api.record(stop);
  if (status != api.success()) return fail(status, "cudaEventRecord");

  status = api.synchronize(stop);
  if (status != api.success()) return fail(status, "cudaEventSynchronize");

  float measured_ms = 0.0f;
  status = api.elapsed(&measured_ms, start, stop);
  if (status != api.success()) return fail(status, "cudaEventElapsedTime");

  if (!cleanup()) return false;
  *elapsed_ms = static_cast<double>(measured_ms);
  return true;
}

}  // namespace bench
