# Host-only tests build everywhere. CUDA tests build only when a toolkit is
# present, and each one returns 0 with SKIPPED on a machine without a device.

add_executable(test_host test_host.cpp)
target_include_directories(test_host PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${PROJECT_SOURCE_DIR}/src
  ${PROJECT_SOURCE_DIR}/include)
cuda_kernels_set_host_warnings(test_host)
add_test(NAME host_reference COMMAND test_host)

add_executable(test_attention_reference test_attention_reference.cpp)
target_include_directories(test_attention_reference PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/src ${PROJECT_SOURCE_DIR}/include)
cuda_kernels_set_host_warnings(test_attention_reference)
add_test(NAME attention_reference COMMAND test_attention_reference)

add_executable(test_device_status test_device_status.cpp)
target_include_directories(test_device_status PRIVATE ${PROJECT_SOURCE_DIR}/src)
cuda_kernels_set_host_warnings(test_device_status)
add_test(NAME device_status COMMAND test_device_status)

add_executable(test_benchmark_options test_benchmark_options.cpp)
target_include_directories(test_benchmark_options PRIVATE
  ${PROJECT_SOURCE_DIR}/benchmarks)
cuda_kernels_set_host_warnings(test_benchmark_options)
add_test(NAME benchmark_options COMMAND test_benchmark_options)

add_executable(test_benchmark_statistics test_benchmark_statistics.cpp)
target_include_directories(test_benchmark_statistics PRIVATE
  ${PROJECT_SOURCE_DIR}/benchmarks)
cuda_kernels_set_host_warnings(test_benchmark_statistics)
add_test(NAME benchmark_statistics COMMAND test_benchmark_statistics)

add_executable(test_benchmark_metadata test_benchmark_metadata.cpp)
target_include_directories(test_benchmark_metadata PRIVATE
  ${PROJECT_SOURCE_DIR}/benchmarks)
cuda_kernels_set_host_warnings(test_benchmark_metadata)
add_test(NAME benchmark_metadata COMMAND test_benchmark_metadata)

add_executable(test_benchmark_checked_copy test_benchmark_checked_copy.cpp)
target_include_directories(test_benchmark_checked_copy PRIVATE
  ${PROJECT_SOURCE_DIR}/benchmarks)
cuda_kernels_set_host_warnings(test_benchmark_checked_copy)
add_test(NAME benchmark_checked_copy COMMAND test_benchmark_checked_copy)

add_executable(test_benchmark_event_timer test_benchmark_event_timer.cpp)
target_include_directories(test_benchmark_event_timer PRIVATE
  ${PROJECT_SOURCE_DIR}/benchmarks)
cuda_kernels_set_host_warnings(test_benchmark_event_timer)
add_test(NAME benchmark_event_timer COMMAND test_benchmark_event_timer)

add_executable(test_benchmark_device_buffer test_benchmark_device_buffer.cpp)
target_include_directories(test_benchmark_device_buffer PRIVATE ${PROJECT_SOURCE_DIR}/benchmarks)
cuda_kernels_set_host_warnings(test_benchmark_device_buffer)
add_test(NAME benchmark_device_buffer COMMAND test_benchmark_device_buffer)

if(CUDA_KERNELS_HAVE_CUDA)
  foreach(name IN ITEMS vecadd reduce softmax gemm layernorm attention)
    add_executable(test_${name} test_${name}.cpp)
    target_include_directories(test_${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/src)
    target_link_libraries(test_${name} PRIVATE cuda_kernels::cudakernels)
    cuda_kernels_set_host_warnings(test_${name})
    add_test(NAME ${name} COMMAND test_${name})
    # Labelled so a GPU run can be selected with `ctest -L gpu`. The label does
    # not make a skip visible: the binaries exit 0 when no device is present, so
    # run runners/test.sh, which detects the SKIPPED output.
    set_tests_properties(${name} PROPERTIES LABELS "gpu")
  endforeach()
endif()
