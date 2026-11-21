#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace bench {

inline double median(std::vector<double> values) {
  if (values.empty()) {
    return 0.0;
  }
  std::sort(values.begin(), values.end());
  const std::size_t mid = values.size() / 2;
  return values.size() % 2 == 0
             ? 0.5 * (values[mid - 1] + values[mid])
             : values[mid];
}

// Uses the nearest-rank convention. p is a fraction in [0, 1]; out-of-range
// finite values select the nearest endpoint. Empty or non-finite input returns 0.
inline double percentile(std::vector<double> values, double p) {
  if (values.empty() || !std::isfinite(p)) {
    return 0.0;
  }
  std::sort(values.begin(), values.end());
  if (p <= 0.0) {
    return values.front();
  }
  if (p >= 1.0) {
    return values.back();
  }
  const std::size_t rank = std::max<std::size_t>(
      1, static_cast<std::size_t>(std::ceil(p * static_cast<double>(values.size()))));
  return values[rank - 1];
}

}  // namespace bench
