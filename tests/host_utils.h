#pragma once

// Host-side reference implementations and comparison helpers. These run on the
// CPU and are what the GPU outputs are checked against; they are also the only
// checks that execute on a machine without a CUDA device.

#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>

namespace host {

inline void fail(const char* test, const std::string& msg) {
  std::fprintf(stderr, "FAIL [%s]: %s\n", test, msg.c_str());
  std::exit(1);
}

inline void check(bool cond, const char* test, const std::string& msg) {
  if (!cond) {
    fail(test, msg);
  }
}

inline std::vector<float> random_floats(std::size_t n, float lo = -1.0f, float hi = 1.0f,
                                        unsigned seed = 1234u) {
  std::mt19937 gen(seed);
  std::uniform_real_distribution<float> dist(lo, hi);
  std::vector<float> v(n);
  for (auto& x : v) {
    x = dist(gen);
  }
  return v;
}

// Vector add reference: c[i] = a[i] + b[i]. Exact for float inputs.
inline std::vector<float> vecadd_reference(const std::vector<float>& a,
                                           const std::vector<float>& b) {
  std::vector<float> c(a.size());
  for (std::size_t i = 0; i < a.size(); ++i) {
    c[i] = a[i] + b[i];
  }
  return c;
}

// Sum accumulated in double regardless of input type, to keep the reference
// itself off the error path being measured.
template <typename T>
inline double sum_reference(const std::vector<T>& v) {
  double acc = 0.0;
  for (const auto& x : v) {
    acc += static_cast<double>(x);
  }
  return acc;
}

// Relative error against a scale of max(|ref|, n). The n term keeps the metric
// meaningful when the true sum is near zero relative to the term count, and
// matches the worst-case growth of accumulated rounding (~n*eps).
inline double rel_error(double ref, double got, std::size_t n) {
  const double denom = std::fmax(std::fabs(ref), static_cast<double>(n));
  return denom == 0.0 ? std::fabs(got) : std::fabs(got - ref) / denom;
}

}  // namespace host
