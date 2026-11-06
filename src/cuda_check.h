#pragma once

#include <cstdio>
#include <cstdlib>
#include <cuda_runtime.h>

// Checks a CUDA API call and a kernel launch. Aborting is deliberate: every
// call site is one whose failure leaves the program in an undefined state.
#define CUDA_CHECK(expr)                                                      \
  do {                                                                        \
    cudaError_t err__ = (expr);                                               \
    if (err__ != cudaSuccess) {                                               \
      std::fprintf(stderr, "CUDA error %s at %s:%d\n", cudaGetErrorString(err__), \
                   __FILE__, __LINE__);                                       \
      std::abort();                                                           \
    }                                                                         \
  } while (0)

#define CUDA_CHECK_LAST_ERROR() CUDA_CHECK(cudaGetLastError())
