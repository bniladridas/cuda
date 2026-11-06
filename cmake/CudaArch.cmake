# Resolves CMAKE_CUDA_ARCHITECTURES and only enables the CUDA language if a
# toolkit is actually present, so CPU-only machines (developer laptops, the
# cpu CI job) configure and build without a CUDA install.

if(NOT CMAKE_CUDA_ARCHITECTURES)
  if(DEFINED ENV{CUDA_KERNELS_ARCH})
    set(CMAKE_CUDA_ARCHITECTURES "$ENV{CUDA_KERNELS_ARCH}" CACHE STRING
      "CUDA architectures to target (semicolon-separated sm_XX values)")
  else()
    # 70 = Volta (T4 / V100), 75 = Turing (T4 / RTX 20xx), 80/86 = Ampere
    # (A10 / A100 / RTX 30xx), 89 = Ada (L4 / RTX 40xx), 90 = Hopper (H100).
    # 70 keeps the source buildable on older CI hardware; SASS is recompiled
    # per-arch so no performance is lost on the target device.
    set(CMAKE_CUDA_ARCHITECTURES "70;75;80;86;89;90" CACHE STRING
      "CUDA architectures to target (semicolon-separated sm_XX values)")
  endif()
endif()

find_package(CUDAToolkit QUIET)

if(CUDAToolkit_FOUND)
  enable_language(CUDA)
  message(STATUS "CUDA toolkit ${CUDAToolkit_VERSION} found; kernels will be built")
  message(STATUS "  CUDA architectures: ${CMAKE_CUDA_ARCHITECTURES}")
elseif(CMAKE_DISABLE_FIND_PACKAGE_CUDAToolkit)
  message(STATUS "CUDA toolkit lookup disabled; kernel targets will not be built")
else()
  message(STATUS "CUDA toolkit not found; kernel targets will not be built "
                 "(configure with -DCUDAToolkit_ROOT to enable)")
endif()

if(TARGET CUDA::toolkit)
  set(CUDA_KERNELS_HAVE_CUDA ON)
else()
  set(CUDA_KERNELS_HAVE_CUDA OFF)
endif()

if(CUDA_KERNELS_HAVE_CUDA)
  # Line-numbered device code aids profiling and crash attribution; keep the
  # generated PTX/SASS honest about optimisation level.
  set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -Xptxas=-v --generate-line-info")
  if(CUDA_KERNELS_WERROR)
    set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -Xcompiler=-Wall,-Wextra,-Werror")
  endif()
  set(CMAKE_CUDA_STANDARD 17)
  set(CMAKE_CUDA_STANDARD_REQUIRED ON)
endif()
