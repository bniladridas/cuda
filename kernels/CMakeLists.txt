# Only defined when a CUDA toolkit is present. Tests and benchmarks that need
# the kernels check CUDA_KERNELS_HAVE_CUDA before linking against this target,
# so CPU-only configurations still build everything host-side.

if(CUDA_KERNELS_HAVE_CUDA)
  add_library(cudakernels STATIC
    ${PROJECT_SOURCE_DIR}/src/vecadd.cu
    ${PROJECT_SOURCE_DIR}/src/reduce.cu)
  target_include_directories(cudakernels
    PUBLIC ${PROJECT_SOURCE_DIR}/include
    PRIVATE ${PROJECT_SOURCE_DIR}/src)
  target_link_libraries(cudakernels PUBLIC CUDA::cudart)
  set_target_properties(cudakernels PROPERTIES
    CUDA_ARCHITECTURES "${CMAKE_CUDA_ARCHITECTURES}"
    POSITION_INDEPENDENT_CODE ON)
  add_library(cuda_kernels::cudakernels ALIAS cudakernels)
endif()
