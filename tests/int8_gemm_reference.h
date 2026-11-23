#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace host {

constexpr std::size_t kInt8GemmMaxSafeK =
    static_cast<std::size_t>(std::numeric_limits<std::int32_t>::max()) / (128U * 128U);

inline std::vector<std::int32_t> gemm_int8_reference(const std::vector<std::int8_t>& a,
                                                     const std::vector<std::int8_t>& b,
                                                     std::size_t m, std::size_t n,
                                                     std::size_t k) {
  if (m == 0 || n == 0 || k == 0) return {};
  if (k > kInt8GemmMaxSafeK || m > std::numeric_limits<std::size_t>::max() / k ||
      k > std::numeric_limits<std::size_t>::max() / n ||
      m > std::numeric_limits<std::size_t>::max() / n || a.size() != m * k ||
      b.size() != k * n) {
    return {};
  }
  std::vector<std::int32_t> output(m * n, 0);
  for (std::size_t row = 0; row < m; ++row) {
    for (std::size_t col = 0; col < n; ++col) {
      std::int32_t accumulator = 0;
      for (std::size_t inner = 0; inner < k; ++inner) {
        accumulator += static_cast<std::int32_t>(a[row * k + inner]) *
                       static_cast<std::int32_t>(b[inner * n + col]);
      }
      output[row * n + col] = accumulator;
    }
  }
  return output;
}

}  // namespace host
