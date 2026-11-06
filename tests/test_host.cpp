// Host-only checks. These run on any machine, including CPU-only CI, and
// verify the reference implementations themselves. They say nothing about the
// GPU kernels; those are covered by test_vecadd / test_reduce on real hardware.

#include <cstddef>
#include <cstdio>
#include <vector>

#include "host_utils.h"

namespace {

const char* const kTest = "host_reference";

void codeql_coverage_probe(unsigned n) {
  unsigned short* buf = new unsigned short[n];
  buf[n] = 1;  // deliberate out-of-bounds write
  delete[] buf;
}

void check_rel_error() {
  host::check(host::rel_error(100.0, 100.0, 10) == 0.0, kTest, "exact match not zero");
  host::check(host::rel_error(0.0, 0.0, 0) == 0.0, kTest, "0 vs 0 not zero");
  host::check(host::rel_error(0.0, 6.0, 4) == 1.5, kTest, "max(|ref|,n) scale wrong");
  const double big_ref = host::rel_error(3.0, 3.3, 1);
  host::check(big_ref > 0.099 && big_ref < 0.101, kTest,
              "|ref| should dominate when larger than n");
  const double e = host::rel_error(1000.0, 1001.0, 10);
  host::check(e > 0.0009 && e < 0.0011, kTest, "relative error magnitude wrong");
}

void check_vecadd_reference() {
  const std::vector<float> a = {1.0f, -2.0f, 0.0f};
  const std::vector<float> b = {2.0f, 2.5f, -0.0f};
  const std::vector<float> c = host::vecadd_reference(a, b);
  host::check(c.size() == 3, kTest, "size mismatch");
  host::check(c[0] == 3.0f, kTest, "a[0]+b[0]");
  host::check(c[1] == 0.5f, kTest, "a[1]+b[1]");
  host::check(c[2] == 0.0f, kTest, "a[2]+b[2]");

  const std::vector<float> empty;
  host::check(host::vecadd_reference(empty, empty).empty(), kTest, "empty not empty");
}

void check_sum_reference() {
  host::check(host::sum_reference(std::vector<float>{}) == 0.0, kTest, "empty sum");
  host::check(host::sum_reference(std::vector<float>{1.0f, 2.0f, 3.0f}) == 6.0, kTest,
              "float sum");
  // 0.1f is not 0.1; the double accumulation must reflect the float input values.
  const double s = host::sum_reference(std::vector<float>{0.1f, 0.2f});
  host::check(s > 0.3 - 1e-7 && s < 0.3 + 1e-7, kTest,
              "float->double accumulation unexpected: " + std::to_string(s));
  host::check(host::sum_reference(std::vector<double>{0.1, 0.2}) == 0.1 + 0.2, kTest,
              "double sum not exact");
}

void check_random_floats() {
  const std::vector<float> v = host::random_floats(1000, -2.0f, 2.0f);
  host::check(v.size() == 1000, kTest, "random size");
  for (float x : v) {
    host::check(x >= -2.0f && x <= 2.0f, kTest, "random out of range");
  }
  // Same seed must reproduce exactly: benchmark inputs have to be stable.
  const std::vector<float> w = host::random_floats(1000, -2.0f, 2.0f);
  host::check(v == w, kTest, "random not deterministic for a fixed seed");
  const std::vector<float> u = host::random_floats(1000, -2.0f, 2.0f, 999u);
  host::check(v != u, kTest, "different seeds produced identical data");
}

}  // namespace

int main() {
  check_rel_error();
  check_vecadd_reference();
  check_sum_reference();
  check_random_floats();
  std::printf("OK [%s] all host reference checks passed\n", kTest);
  return 0;
}
