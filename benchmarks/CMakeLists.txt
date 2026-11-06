# Benchmarks require the real kernels and a device at run time. Without a
# toolkit there is nothing to measure, so the target is simply not created.

if(CUDA_KERNELS_HAVE_CUDA)
  add_executable(cuda_benchmarks ${CMAKE_CURRENT_SOURCE_DIR}/main_bench.cpp)
  target_include_directories(cuda_benchmarks
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/src
            ${PROJECT_SOURCE_DIR}/tests)
  target_link_libraries(cuda_benchmarks PRIVATE cuda_kernels::cudakernels)

  # Not a ctest test: timing is not a correctness assertion. Correctness is
  # gated inside the binary before it prints any performance figure.
endif()
