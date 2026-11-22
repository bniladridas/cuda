// Host-only checks. These run on any machine, including CPU-only CI, and
// verify the reference implementations themselves. They say nothing about the
// GPU kernels; those are covered by the GPU tests on real hardware.

#include <cstddef>
#include <cstdio>
#include <limits>
#include <string>
#include <vector>

#include "cuda_kernels/gemm.cuh"
#include "cuda_kernels/layernorm.cuh"
#include "cuda_kernels/reduce.cuh"
#include "cuda_kernels/vecadd.cuh"

#include "host_utils.h"

namespace {

const char* const kTest = "host_reference";

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

void check_gemm_reference() {
  const std::vector<float> a = {1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f};
  const std::vector<float> b = {7.0f, 8.0f, 9.0f, 10.0f, 11.0f, 12.0f};
  const auto c = host::gemm_fp32_reference(a, b, 2, 2, 3);
  host::check(c.size() == 4, kTest, "GEMM output size");
  host::check(c[0] == 58.0f && c[1] == 64.0f && c[2] == 139.0f && c[3] == 154.0f, kTest,
              "GEMM row-major reference values");
  const auto one = host::gemm_fp32_reference({2.0f}, {3.0f}, 1, 1, 1);
  host::check(one.size() == 1 && one[0] == 6.0f, kTest, "GEMM scalar case");
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

void check_softmax_reference() {
  const std::vector<float> input = {1000.0f, 1001.0f, 999.0f,
                                    -1000.0f, -999.0f, -1001.0f};
  const auto output = host::softmax_reference(input, 2, 3);
  host::check(output.size() == input.size(), kTest, "softmax output size");
  for (std::size_t row = 0; row < 2; ++row) {
    double sum = 0.0;
    for (std::size_t col = 0; col < 3; ++col) {
      const float v = output[row * 3 + col];
      host::check(std::isfinite(v) && v >= 0.0f, kTest,
                  "softmax finite and non-negative");
      sum += v;
    }
    host::check(std::fabs(sum - 1.0) < 1e-6, kTest, "softmax row sum");
  }
  host::check(host::softmax_reference({}, 0, 3).empty(), kTest, "zero-row softmax");
  host::check(host::softmax_reference({}, 3, 0).empty(), kTest, "zero-column softmax");
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

void check_layernorm_reference() {
  const auto output = host::layernorm_reference({1.0f, 2.0f, 3.0f, 4.0f}, {1.0f, 1.0f},
                                                {0.0f, 0.0f}, 2, 2, 1.0e-5f);
  host::check(output.size() == 4, kTest, "layernorm output size");
  host::check(std::fabs(output[0] + output[1]) < 1.0e-5f, kTest,
              "layernorm first row is not centered");
  host::check(std::fabs(output[2] + output[3]) < 1.0e-5f, kTest,
              "layernorm second row is not centered");
  const auto constant = host::layernorm_reference(
      std::vector<float>(4, 7.0f), {2.0f, 3.0f}, {1.0f, -1.0f}, 2, 2, 1.0e-5f);
  host::check(constant[0] == 1.0f && constant[1] == -1.0f && constant[2] == 1.0f &&
                  constant[3] == -1.0f,
              kTest, "constant-row layernorm should produce beta");
  host::check(host::layernorm_reference({}, {}, {}, 0, 3, 1.0e-5f).empty(), kTest,
              "zero-row layernorm");

  host::check(cuda_kernels::detail::is_valid_layernorm_epsilon(1.0e-5f), kTest,
              "positive finite epsilon rejected");
  host::check(!cuda_kernels::detail::is_valid_layernorm_epsilon(0.0f), kTest,
              "zero epsilon accepted");
  host::check(!cuda_kernels::detail::is_valid_layernorm_epsilon(-1.0f), kTest,
              "negative epsilon accepted");
  host::check(!cuda_kernels::detail::is_valid_layernorm_epsilon(
                  std::numeric_limits<float>::infinity()),
              kTest, "infinite epsilon accepted");
  host::check(!cuda_kernels::detail::is_valid_layernorm_epsilon(
                  std::numeric_limits<float>::quiet_NaN()),
              kTest, "NaN epsilon accepted");
}

}  // namespace

int main() {
  check_rel_error();
  check_vecadd_reference();
  check_gemm_reference();
  check_sum_reference();
  check_random_floats();
  check_softmax_reference();
  check_layernorm_reference();
  std::printf("OK [%s] all host reference checks passed\n", kTest);
  return 0;
}
