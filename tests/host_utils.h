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

// Row-major FP32 GEMM reference. Accumulating in double keeps the reference
// independent of the kernel's FP32 fused-multiply-add accumulation order.
inline std::vector<float> gemm_fp32_reference(const std::vector<float>& a,
                                              const std::vector<float>& b, std::size_t m,
                                              std::size_t n, std::size_t k) {
  std::vector<float> c(m * n, 0.0f);
  for (std::size_t row = 0; row < m; ++row) {
    for (std::size_t col = 0; col < n; ++col) {
      double acc = 0.0;
      for (std::size_t inner = 0; inner < k; ++inner) {
        acc += static_cast<double>(a[row * k + inner]) *
               static_cast<double>(b[inner * n + col]);
      }
      c[row * n + col] = static_cast<float>(acc);
    }
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

inline std::vector<float> softmax_reference(const std::vector<float>& input,
                                            std::size_t rows, std::size_t columns) {
  if (rows == 0 || columns == 0) {
    return {};
  }
  if (input.size() != rows * columns) {
    fail("softmax_reference", "shape mismatch");
  }
  std::vector<float> output(input.size());
  for (std::size_t row = 0; row < rows; ++row) {
    const std::size_t offset = row * columns;
    float maximum = input[offset];
    for (std::size_t col = 1; col < columns; ++col) {
      maximum = std::fmax(maximum, input[offset + col]);
    }
    double denominator = 0.0;
    for (std::size_t col = 0; col < columns; ++col) {
      output[offset + col] = std::exp(input[offset + col] - maximum);
      denominator += output[offset + col];
    }
    for (std::size_t col = 0; col < columns; ++col) {
      output[offset + col] = static_cast<float>(output[offset + col] / denominator);
    }
  }
  return output;
}
inline std::vector<float> layernorm_reference(const std::vector<float>& input,
                                              const std::vector<float>& gamma,
                                              const std::vector<float>& beta,
                                              std::size_t rows, std::size_t features,
                                              float epsilon) {
  if (rows == 0 || features == 0) return {};
  if (input.size() != rows * features || gamma.size() != features ||
      beta.size() != features || !(epsilon > 0.0f) || !std::isfinite(epsilon)) {
    fail("layernorm_reference", "invalid shape or epsilon");
  }
  std::vector<float> output(input.size());
  for (std::size_t row = 0; row < rows; ++row) {
    const std::size_t offset = row * features;
    double sum = 0.0;
    for (std::size_t col = 0; col < features; ++col)
      sum += static_cast<double>(input[offset + col]);
    const double mean = sum / static_cast<double>(features);
    double squared_deviation = 0.0;
    for (std::size_t col = 0; col < features; ++col) {
      const double delta = static_cast<double>(input[offset + col]) - mean;
      squared_deviation += delta * delta;
    }
    const double variance = squared_deviation / static_cast<double>(features);
    const double inverse_stddev = 1.0 / std::sqrt(variance + static_cast<double>(epsilon));
    for (std::size_t col = 0; col < features; ++col) {
      const double normalized =
          (static_cast<double>(input[offset + col]) - mean) * inverse_stddev;
      output[offset + col] =
          static_cast<float>(normalized * static_cast<double>(gamma[col]) + beta[col]);
    }
  }
  return output;
}

}  // namespace host
