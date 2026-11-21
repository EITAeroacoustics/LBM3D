cmake_minimum_required(VERSION 3.25)

project(LBM3D LANGUAGES CXX)

set(LBM_DIM 3 CACHE STRING "AMReX spatial dimension (2 or 3)")
if (NOT LBM_DIM MATCHES "^[23]$")
    message(FATAL_ERROR "LBM_DIM must be 2 or 3")
endif ()

find_package(AMReX REQUIRED)
if (NOT TARGET AMReX::amrex_${LBM_DIM}d)
    message(FATAL_ERROR "The AMReX installation has no ${LBM_DIM}D library")
endif ()
if (AMReX_CUDA)
    enable_language(CUDA)
    include(AMReXTargetHelpers)
endif ()

add_library(lbm3d STATIC
    Source/AMReXAdapter/AmrCoreLBM.cpp
    Source/AMReXAdapter/AdvanceLBMAtLevel.cpp
    Source/Boundary/BC/bc_val.cpp
    Source/Boundary/IBM/IBMarkerDF.cpp
    Source/Boundary/IBM/IBForceEval.cpp
    Source/Boundary/LevelSet/LevelSet.cpp
    Source/Diagnostics/AmrCoreLBMForce.cpp
    Source/Diagnostics/AmrCoreLBMOutput.cpp)
target_link_libraries(lbm3d PUBLIC AMReX::amrex_${LBM_DIM}d)
target_include_directories(lbm3d
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/AMReXAdapter
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Boundary
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/LBM
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Boundary/BC
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Diagnostics
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Utils)
if (AMReX_CUDA)
    setup_target_for_cuda_compilation(lbm3d)
endif ()

function(add_lbm_case target case_dir)
    add_executable(${target}
        Examples/Common/main.cpp
        Examples/Common/ProblemInit.cpp)
    target_include_directories(${target} PRIVATE ${case_dir})
    target_link_libraries(${target} PRIVATE lbm3d)
    if (AMReX_CUDA)
        setup_target_for_cuda_compilation(${target})
    endif ()
endfunction()

if (LBM_DIM EQUAL 2)
    add_lbm_case(lbm3d_cavity
        ${CMAKE_CURRENT_SOURCE_DIR}/iLBMReX/Examples/Cavity_flow)
    add_lbm_case(lbm3d_pitching_airfoil
        ${CMAKE_CURRENT_SOURCE_DIR}/iLBMReX/Examples/Pitching_airfoil)
else ()
    add_lbm_case(lbm3d_tgv3d
        ${CMAKE_CURRENT_SOURCE_DIR}/Benchmarks/TGV3D)
endif ()
