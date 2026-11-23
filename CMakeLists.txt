cmake_minimum_required(VERSION 3.25)

project(LBM3D LANGUAGES CXX)

option(LBM_TIMING "Measure synchronized steps 101-600 in a build-local core copy" OFF)
option(LBM_ENABLE_IBM "Compile the original IBM coupling into the solver" ON)

find_package(AMReX REQUIRED)
if (NOT TARGET AMReX::amrex_3d)
    message(FATAL_ERROR "LBM3D requires a 3D AMReX installation")
endif ()
if (NOT AMReX_CUDA)
    message(FATAL_ERROR "LBM3D requires AMReX with CUDA")
endif ()
enable_language(CUDA)
include(AMReXTargetHelpers)

set(lbm_core_file Source/AMReXAdapter/AmrCoreLBM.cpp)
if (LBM_TIMING)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    set(lbm_core_file "${CMAKE_CURRENT_BINARY_DIR}/timed/AmrCoreLBM.cpp")
    file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/timed")
    execute_process(
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/Baseline/make_timed_core.py"
                "${CMAKE_CURRENT_SOURCE_DIR}/Source/AMReXAdapter/AmrCoreLBM.cpp" "${lbm_core_file}"
        COMMAND_ERROR_IS_FATAL ANY)
endif ()

add_library(lbm3d STATIC
    ${lbm_core_file}
    Source/AMReXAdapter/AdvanceLBMAtLevel.cpp
    Source/AMReXAdapter/DirectionalHalo.cpp
    Source/Boundary/BC/bc_val.cpp
    Source/Boundary/IBM/IBMarkerDF.cpp
    Source/Boundary/IBM/IBForceEval.cpp
    Source/Boundary/LevelSet/LevelSet.cpp
    Source/Diagnostics/AmrCoreLBMForce.cpp
    Source/Diagnostics/AmrCoreLBMOutput.cpp)
target_link_libraries(lbm3d PUBLIC AMReX::amrex_3d)
if (LBM_ENABLE_IBM)
    target_compile_definitions(lbm3d PRIVATE LBM_USE_IBM=1)
else ()
    target_compile_definitions(lbm3d PRIVATE LBM_USE_IBM=0)
endif ()
target_include_directories(lbm3d
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/AMReXAdapter
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Boundary
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/LBM
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Boundary/BC
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Diagnostics
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Utils)
setup_target_for_cuda_compilation(lbm3d)

function(add_lbm_case target case_dir)
    add_executable(${target}
        Examples/Common/main.cpp
        Examples/Common/ProblemInit.cpp)
    target_include_directories(${target} PRIVATE ${case_dir})
    target_link_libraries(${target} PRIVATE lbm3d)
    setup_target_for_cuda_compilation(${target})
endfunction()

add_executable(lbm_compare Benchmarks/TGV3D/compare.cpp)
target_link_libraries(lbm_compare PRIVATE AMReX::amrex_3d)
setup_target_for_cuda_compilation(lbm_compare)

add_lbm_case(lbm3d_sphere ${CMAKE_CURRENT_SOURCE_DIR}/Examples/Sphere_flow)
add_lbm_case(lbm3d_square_duct ${CMAKE_CURRENT_SOURCE_DIR}/Examples/SquareDuct_flow)
add_executable(lbm3d_tgv3d
    Examples/Common/main.cpp
    Benchmarks/TGV3D/ProblemInit.cpp)
target_include_directories(lbm3d_tgv3d PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/Benchmarks/TGV3D)
target_link_libraries(lbm3d_tgv3d PRIVATE lbm3d)
setup_target_for_cuda_compilation(lbm3d_tgv3d)

add_executable(lbm3d_tgv3d_summary EXCLUDE_FROM_ALL
    Benchmarks/TGV3D/field_summary.cpp
    Benchmarks/TGV3D/ProblemInit.cpp)
target_include_directories(lbm3d_tgv3d_summary PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/Benchmarks/TGV3D)
target_compile_definitions(lbm3d_tgv3d_summary PRIVATE LBM_TGV_METRICS=1)
target_link_libraries(lbm3d_tgv3d_summary PRIVATE lbm3d)
setup_target_for_cuda_compilation(lbm3d_tgv3d_summary)

add_executable(lbm3d_square_duct_summary EXCLUDE_FROM_ALL
    Benchmarks/TGV3D/field_summary.cpp
    Examples/Common/ProblemInit.cpp)
target_include_directories(lbm3d_square_duct_summary PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/Examples/SquareDuct_flow)
target_link_libraries(lbm3d_square_duct_summary PRIVATE lbm3d)
setup_target_for_cuda_compilation(lbm3d_square_duct_summary)

add_executable(lbm3d_sphere_summary EXCLUDE_FROM_ALL
    Benchmarks/TGV3D/field_summary.cpp
    Examples/Common/ProblemInit.cpp)
target_include_directories(lbm3d_sphere_summary PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/Examples/Sphere_flow)
target_link_libraries(lbm3d_sphere_summary PRIVATE lbm3d)
setup_target_for_cuda_compilation(lbm3d_sphere_summary)
