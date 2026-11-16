cmake_minimum_required(VERSION 3.24)

project(cuda_kernels
  VERSION 0.1.0
  DESCRIPTION "CUDA C++ kernel engineering: correctness, optimization, reproducible benchmarks"
  LANGUAGES CXX)

option(CUDA_KERNELS_BUILD_TESTS "Build correctness tests" ON)
option(CUDA_KERNELS_BUILD_BENCHMARKS "Build the benchmark binary" ON)
option(CUDA_KERNELS_WERROR "Treat compiler warnings as errors" ON)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(cmake/CompilerWarnings.cmake)
include(cmake/CudaArch.cmake)

add_subdirectory(kernels)

if(CUDA_KERNELS_BUILD_TESTS)
  include(CTest)
  add_subdirectory(tests)
endif()

if(CUDA_KERNELS_BUILD_BENCHMARKS)
  add_subdirectory(benchmarks)
endif()
