# Host-only tests build everywhere. CUDA tests build only when a toolkit is
# present, and each one returns 0 with SKIPPED on a machine without a device.

add_executable(test_host test_host.cpp)
target_include_directories(test_host PRIVATE ${CMAKE_CURRENT_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/src)
add_test(NAME host_reference COMMAND test_host)

if(CUDA_KERNELS_HAVE_CUDA)
  foreach(name IN ITEMS vecadd reduce)
    add_executable(test_${name} test_${name}.cpp)
    target_include_directories(test_${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_link_libraries(test_${name} PRIVATE cuda_kernels::cudakernels)
    add_test(NAME ${name} COMMAND test_${name})
    # Labelled so a GPU run can be selected with `ctest -L gpu` and so the
    # SKIPPED output stays visible in summaries rather than looking like a pass.
    set_tests_properties(${name} PROPERTIES LABELS "gpu")
  endforeach()
endif()
