# C, C++ and Fortran roadmap

## Decision

Keep **CUDA C++ as the sole implementation language for the kernel core**.
Do not add C or Fortran source targets to the default build yet.

| Track | Decision | Reason |
| --- | --- | --- |
| CUDA C++ | Adopt, current core | The existing kernels, launchers, tests and benchmark harness are already C++17/CUDA. |
| C interoperability | Defer, preserve an option | The public launcher headers already avoid CUDA types, but there is no demonstrated C caller or ABI consumer that justifies freezing a C ABI today. |
| Fortran | Defer | There is no current Fortran caller, numerical workload, compiler lane or GPU validation environment. A separate experiment can be justified later without changing the core. |

This is an engineering decision, not a language-count target. Revisit it when a concrete consumer or workload appears.

## Current architecture

### Public surface and portability boundary

- `include/cuda_kernels/vecadd.cuh` declares `launch_vecadd`.
- `include/cuda_kernels/reduce.cuh` declares float and double `launch_reduce` overloads and the compile-time `launch_reduce_scratch_elems` helper.
- Both headers use standard C++ headers and `std::size_t`. The stream is represented as `void*`, so the public declarations do not expose `cudaStream_t` or require CUDA headers.
- The pointer arguments are device-memory pointers. The current interface does not allocate or own those buffers. The reduction caller supplies scratch sized using the documented helper.
- The declarations are C++ namespaced functions, not a C ABI. Avoid describing them as C-compatible merely because CUDA types are hidden.

### Implementations and host references

- `src/vecadd.cu` contains the grid-stride vector-add kernel and its launcher.
- `src/reduce.cu` contains the two-pass float/double reduction, warp and block reduction helpers, and launchers.
- `tests/test_host.cpp` provides CPU-side reference checks. `tests/test_vecadd.cpp` and `tests/test_reduce.cpp` exercise the CUDA implementations when a toolkit is available.
- The reduction is tolerance-checked because floating-point accumulation order can change with launch geometry. The implementation does not promise bitwise reproducibility across devices or configurations.

### Build, CI and benchmark boundary

- The top-level `CMakeLists.txt` declares CXX as the project language. `cmake/CudaArch.cmake` probes for the CUDA toolkit and enables CUDA only when it is present.
- `kernels/CMakeLists.txt` creates the kernel library only when CUDA is available. `tests/CMakeLists.txt` always builds host tests and adds device tests conditionally. `benchmarks/CMakeLists.txt` similarly creates the benchmark binary only with a CUDA toolkit.
- The hosted CPU CI configures with CUDA toolkit discovery disabled, builds host targets, runs reference tests and Python tooling checks. The separate GPU job requires a configured self-hosted NVIDIA runner and is gated by `CUDA_CI_ENABLED`.
- The benchmark harness verifies results against CPU references before timing and records device/toolchain provenance. No GPU compilation, execution or performance result should be claimed until a real device run is recorded.

## C interoperability assessment

### Potential value

A C ABI could serve non-C++ host applications, stable plugin boundaries, or language bindings that cannot consume C++ name mangling and overloads. None of those consumers is currently demonstrated in this repository.

### Proposed boundary, only if a consumer appears

Prefer a small opaque, versionable C header such as `include/cuda_kernels/c_api.h`, implemented by a C++ translation unit that delegates to the existing launchers. Keep CUDA implementation details private.

Before adopting it, specify and test:

1. **ABI:** `extern "C"` declarations, fixed-width/status types, explicit API versioning, and no C++ types, templates, overloads, or exceptions crossing the boundary.
2. **Ownership:** caller-owned device buffers and stream lifetime, explicit scratch requirements for reduction, and no hidden allocation unless a separate API contract defines it.
3. **Errors:** return status codes; define how CUDA launch errors are surfaced and whether asynchronous execution errors require an explicit synchronization or query API. Never allow a C++ exception to cross the ABI.
4. **Build:** compile a real C translation unit against the header, link it to the C++ implementation with the C++ linker/runtime, and keep the target optional until the contract is stable.
5. **Tests:** C compile/link smoke test, invalid-argument and error-path tests, ABI symbol inspection where useful, plus device correctness tests on NVIDIA hardware.

Do not duplicate the kernels in C. A C reference implementation is also not currently justified: the existing host reference is C++, and a second implementation should be added only to satisfy a concrete C-only consumer or independent validation need.

## Fortran assessment

The lowest-coupling future route is likely ISO_C_BINDING to a deliberately designed C ABI, not a second set of CUDA kernels. That route still depends on the C ABI decision above.

A separate Fortran numerical example could demonstrate interoperability, but it must remain outside the default core build. Before starting it, identify a real workload and select a compiler/toolchain that can be installed in CI and used by contributors. Evaluate:

- compiler availability and licensing/distribution constraints;
- ISO_C_BINDING support for the chosen scalar, pointer and status representations;
- how device pointers and stream handles cross the boundary without transferring ownership implicitly;
- whether the example is CPU-only interoperability or genuinely CUDA Fortran, which has a different compiler/toolkit dependency;
- automated compile/link tests and, for GPU execution, a real NVIDIA device lane;
- ongoing maintenance cost relative to the demonstrated numerical use case.

Do not imply that ordinary Fortran support validates CUDA Fortran, or that a CPU-only Fortran example validates device kernels.

## Staged roadmap

| Stage | Work | Acceptance evidence |
| --- | --- | --- |
| 0. Baseline audit | Record current API, kernel, host-reference, build, CI and benchmark boundaries. | This document stays aligned with source and workflow changes; GPU status remains explicit. |
| 1. C consumer gate | Identify a real C caller and freeze only the minimum ABI it needs. If no caller exists, keep C deferred. | Written use case and ABI contract; C compile/link smoke test; ownership and error semantics; CPU tests; GPU tests when hardware is available. |
| 2. Fortran feasibility | Compare a Fortran-to-C binding example with CUDA Fortran only if a concrete workload requires it. | Named compiler/toolchain, isolated example, reproducible compile/link CI, explicit CPU/GPU validation split and maintenance owner. |
| 3. Adoption decision | Review evidence and decide adopt, defer or reject each track. | Follow-up implementation issue(s), measurable scope, CI requirements and no changes to the core until the gate is met. |
| Kernel evolution | Continue CUDA C++ work independently: matrix multiplication/tiling, shared-memory and occupancy study, then profiling-led optimization. | Correctness first; benchmark only on recorded NVIDIA hardware with environment and commit provenance. |

## Non-goals and validation limits

- No rewrite of the existing kernels in C or Fortran.
- No extra language targets merely to increase repository language count.
- No untestable compiler scaffolding in the default build.
- No claims of GPU correctness or performance from CPU-only CI.
- No C ABI promise until ownership, error handling and a real consumer are established.
- No CUDA Fortran claim from a standard Fortran interoperability example.
