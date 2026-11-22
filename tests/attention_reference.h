#pragma once

#include <cmath>
#include <cstddef>
#include <vector>

namespace host {

inline std::vector<float> attention_reference(const std::vector<float>& q,
                                              const std::vector<float>& k,
                                              const std::vector<float>& v,
                                              std::size_t lq, std::size_t lk,
                                              std::size_t d, std::size_t dv) {
  if (lq == 0 || lk == 0 || d == 0 || dv == 0 ||
      q.size() != lq * d || k.size() != lk * d || v.size() != lk * dv) {
    return {};
  }
  std::vector<float> output(lq * dv, 0.0f);
  const double scale = 1.0 / std::sqrt(static_cast<double>(d));
  std::vector<double> weights(lk);
  for (std::size_t row = 0; row < lq; ++row) {
    double maximum = -INFINITY;
    for (std::size_t key = 0; key < lk; ++key) {
      double dot = 0.0;
      for (std::size_t inner = 0; inner < d; ++inner) {
        dot += static_cast<double>(q[row * d + inner]) *
               static_cast<double>(k[key * d + inner]);
      }
      weights[key] = dot * scale;
      if (weights[key] > maximum) maximum = weights[key];
    }
    double denominator = 0.0;
    for (double& weight : weights) {
      weight = std::exp(weight - maximum);
      denominator += weight;
    }
    for (double& weight : weights) weight /= denominator;
    for (std::size_t col = 0; col < dv; ++col) {
      double acc = 0.0;
      for (std::size_t key = 0; key < lk; ++key) {
        acc += weights[key] * static_cast<double>(v[key * dv + col]);
      }
      output[row * dv + col] = static_cast<float>(acc);
    }
  }
  return output;
}

}  // namespace host
