#pragma once
#include <cstddef>
#include <utility>
namespace bench {
template <typename Api, typename T, typename ErrorHandler>
class DeviceBuffer {
 public:
  DeviceBuffer(Api& api, ErrorHandler report) : api_(api), report_(std::move(report)) {}
  DeviceBuffer(const DeviceBuffer&) = delete;
  DeviceBuffer& operator=(const DeviceBuffer&) = delete;
  ~DeviceBuffer() { reset(); }
  bool allocate(std::size_t bytes, const char* operation) {
    if (pointer_) return false;
    const auto status = api_.allocate(&pointer_, bytes);
    if (status != api_.success()) {
      pointer_ = nullptr;
      report_(status, operation);
      return false;
    }
    return true;
  }
  bool reset() {
    if (!pointer_) return true;
    T* owned = pointer_;
    pointer_ = nullptr;
    const auto status = api_.release(owned);
    if (status != api_.success()) {
      report_(status, "cudaFree");
      return false;
    }
    return true;
  }
  T* get() const { return pointer_; }
 private:
  Api& api_;
  ErrorHandler report_;
  T* pointer_ = nullptr;
};
}  // namespace bench
