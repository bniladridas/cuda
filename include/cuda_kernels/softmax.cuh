#pragma once

#include <cstddef>

namespace cuda_kernels {

// Stable row-wise softmax for a contiguous row-major FP32 matrix [rows, columns].
// For positive dimensions, input and output each reference rows * columns floats
// and must not overlap. If either dimension is zero, this launcher is a no-op
// and neither pointer is accessed. Arbitrary positive column counts are valid.
// One block processes each row; rows must fit the device grid-x dimension.
//
// Launches asynchronously on stream (cudaStream_t as void*). Synchronize that
// stream before consuming output. Immediate launch errors are fail-fast;
// asynchronous execution errors may surface at synchronization.
void launch_softmax(const float* input, float* output, std::size_t rows,
                    std::size_t columns, void* stream);

}  // namespace cuda_kernels
