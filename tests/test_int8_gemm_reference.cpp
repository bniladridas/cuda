#include <cstdint>
#include <cstdio>
#include <vector>

#include "int8_gemm_reference.h"

int main() {
  const auto result =
      host::gemm_int8_reference({1, -2, 3, 4, -5, 6}, {7, 8, -9, 10, 11, -12}, 2, 2, 3);
  if (result != std::vector<std::int32_t>({58, -48, 139, -90})) return 1;

  const auto extremes = host::gemm_int8_reference(
      std::vector<std::int8_t>(4, static_cast<std::int8_t>(-128)),
      std::vector<std::int8_t>(4, static_cast<std::int8_t>(-128)), 2, 2, 2);
  if (extremes != std::vector<std::int32_t>({32768, 32768, 32768, 32768})) return 1;

  if (host::kInt8GemmMaxSafeK != 131071) return 1;
  if (!host::gemm_int8_reference({}, {}, 0, 3, 4).empty()) return 1;
  if (!host::gemm_int8_reference({1}, {1}, 1, 1, host::kInt8GemmMaxSafeK + 1).empty())
    return 1;

  // For symmetric quantization, the output scale is the product of input scales.
  const double dequantized = static_cast<double>(result[0]) * (0.25 * 0.5);
  if (dequantized != 7.25) return 1;
  std::puts("OK [int8-gemm-reference] exact accumulation, bounds, and scale semantics");
  return 0;
}
