#include <cmath>
#include <cstdio>
#include <vector>

#include "attention_reference.h"
#include "host_utils.h"

int main() {
  const auto output = host::attention_reference(
      {1.0f, 0.0f, 0.0f, 1.0f}, {1.0f, 0.0f, 0.0f, 1.0f},
      {2.0f, 4.0f, 6.0f, 8.0f}, 2, 2, 2, 2);
  host::check(output.size() == 4, "attention_reference", "output shape");
  for (float value : output) {
    host::check(std::isfinite(value), "attention_reference", "non-finite output");
  }
  const auto empty = host::attention_reference({}, {}, {}, 0, 2, 2, 2);
  host::check(empty.empty(), "attention_reference", "zero query length");
  const auto stable = host::attention_reference(
      {1000.0f, 1000.0f}, {1000.0f, 999.0f, -1000.0f, -999.0f},
      {1.0f, 2.0f, 3.0f, 4.0f}, 1, 2, 2, 2);
  host::check(stable.size() == 2 && std::isfinite(stable[0]) &&
                  std::isfinite(stable[1]),
              "attention_reference", "stable large logits");
  std::printf("OK [attention_reference] all host checks passed\n");
  return 0;
}
