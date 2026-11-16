# Host-only warning flags. Never add these globally: CUDA language rules would
# receive them and nvcc would get host-only flags it cannot use.
function(cuda_kernels_set_host_warnings target)
  if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
    target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    if(CUDA_KERNELS_WERROR)
      target_compile_options(${target} PRIVATE -Werror)
    endif()
  endif()
endfunction()
