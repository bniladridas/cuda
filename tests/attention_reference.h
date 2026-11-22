#pragma once

#include <cmath>
#include <cstddef>
#include <vector>

namespace host {

inline void attention_reference_intermediates(const std::vector<float>& q,
                                              const std::vector<float>& k,
                                              std::size_t lq, std::size_t lk,
                                              std::size_t d,
                                              std::vector<double>* scores,
                                              std::vector<double>* probabilities) {
  scores->assign(lq * lk, 0.0);
  probabilities->assign(lq * lk, 0.0);
  const double scale = 1.0 / std::sqrt(static_cast<double>(d));
  std::vector<double> row_weights(lk);
  for (std::size_t row = 0; row < lq; ++row) {
    double maximum = -INFINITY;
    for (std::size_t key = 0; key < lk; ++key) {
      double dot = 0.0;
      for (std::size_t inner = 0; inner < d; ++inner) {
        dot += static_cast<double>(q[row * d + inner]) *
               static_cast<double>(k[key * d + inner]);
      }
      const double score = dot * scale;
      (*scores)[row * lk + key] = score;
      row_weights[key] = score;
      if (score > maximum) maximum = score;
    }
    double denominator = 0.0;
    for (double& weight : row_weights) {
      weight = std::exp(weight - maximum);
      denominator += weight;
    }
    for (std::size_t key = 0; key < lk; ++key) {
      (*probabilities)[row * lk + key] = row_weights[key] / denominator;
    }
  }
}

inline std::vector<float> attention_reference(const std::vector<float>& q,
                                              const std::vector<float>& k,
                                              const std::vector<float>& v, std::size_t lq,
                                              std::size_t lk, std::size_t d,
                                              std::size_t dv) {
  if (lq == 0 || lk == 0 || d == 0 || dv == 0 || q.size() != lq * d ||
      k.size() != lk * d || v.size() != lk * dv) {
    return {};
  }
  std::vector<double> scores;
  std::vector<double> probabilities;
  attention_reference_intermediates(q, k, lq, lk, d, &scores, &probabilities);
  std::vector<float> output(lq * dv, 0.0f);
  for (std::size_t row = 0; row < lq; ++row) {
    for (std::size_t col = 0; col < dv; ++col) {
      double acc = 0.0;
      for (std::size_t key = 0; key < lk; ++key) {
        acc += probabilities[row * lk + key] *
               static_cast<double>(v[key * dv + col]);
      }
      output[row * dv + col] = static_cast<float>(acc);
    }
  }
  return output;
}

}  // namespace host
