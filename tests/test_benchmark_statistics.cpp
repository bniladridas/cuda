#include <cmath>
#include <cstdio>
#include <limits>
#include <string>
#include <vector>

#include "statistics.h"

namespace {

int failures = 0;

void check(bool condition, const std::string& message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL [benchmark_statistics] %s\n", message.c_str());
    ++failures;
  }
}

void tests_empty_and_singleton_samples() {
  check(bench::median({}) == 0.0, "empty median should be zero");
  check(bench::percentile({}, 0.90) == 0.0, "empty percentile should be zero");
  check(bench::median({4.5}) == 4.5, "singleton median changed");
  check(bench::percentile({4.5}, 0.90) == 4.5, "singleton percentile changed");
}

void tests_nearest_rank_percentiles() {
  check(bench::percentile({7, 1, 6, 2, 5, 3, 4}, 0.90) == 7.0,
        "seven-sample p90 should select the maximum");
  check(bench::percentile({4, 1, 3, 2}, 0.90) == 4.0,
        "four-sample p90 should select the maximum");
  check(bench::percentile({4, 1, 3, 2}, 0.50) == 2.0,
        "even-sample p50 should use nearest rank");
  check(bench::percentile({4, 1, 3, 2}, 1e-300) == 1.0,
        "small positive percentile should select the minimum");
  check(bench::percentile({4, 1, 3, 2}, 0.0) == 1.0,
        "zero percentile should select the minimum");
  check(bench::percentile({4, 1, 3, 2}, 1.0) == 4.0,
        "100th percentile should select the maximum");
}

void tests_median_and_invalid_percentile() {
  check(bench::median({4, 1, 3, 2}) == 2.5, "even-sample median changed");
  check(bench::median({5, 1, 3}) == 3.0, "odd-sample median changed");
  check(bench::percentile({1, 2, 3},
                          std::numeric_limits<double>::quiet_NaN()) == 0.0,
        "non-finite percentile should return zero");
}

}  // namespace

int main() {
  tests_empty_and_singleton_samples();
  tests_nearest_rank_percentiles();
  tests_median_and_invalid_percentile();
  if (failures != 0) {
    std::fprintf(stderr, "benchmark_statistics: %d failure(s)\n", failures);
    return 1;
  }
  std::printf("OK [benchmark_statistics] all statistics checks passed\n");
  return 0;
}
