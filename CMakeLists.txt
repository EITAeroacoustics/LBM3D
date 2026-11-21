cmake_minimum_required(VERSION 3.25)

project(LBM3D LANGUAGES CXX)

set(LBM_DIM 3 CACHE STRING "AMReX spatial dimension (2 or 3)")
option(LBM_TIMING "Measure synchronized steps 101-600 in a build-local core copy" OFF)
option(LBM_ENABLE_IBM "Compile the original IBM coupling into the solver" ON)
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
    Source/Boundary/BC/bc_val.cpp
    Source/Boundary/IBM/IBMarkerDF.cpp
    Source/Boundary/IBM/IBForceEval.cpp
    Source/Boundary/LevelSet/LevelSet.cpp
    Source/Diagnostics/AmrCoreLBMForce.cpp
    Source/Diagnostics/AmrCoreLBMOutput.cpp)
target_link_libraries(lbm3d PUBLIC AMReX::amrex_${LBM_DIM}d)
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

add_executable(lbm_compare Benchmarks/TGV3D/compare.cpp)
target_link_libraries(lbm_compare PRIVATE AMReX::amrex_${LBM_DIM}d)
if (AMReX_CUDA)
    setup_target_for_cuda_compilation(lbm_compare)
endif ()

if (LBM_DIM EQUAL 2)
    add_executable(lbm3d_motion_original Examples/Pitching_airfoil/marker_motion.cpp)
    target_compile_definitions(lbm3d_motion_original PRIVATE LBM_UPSTREAM_GEOMETRY=1)
    target_include_directories(lbm3d_motion_original PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/iLBMReX/Examples/Pitching_airfoil
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Boundary)
    target_link_libraries(lbm3d_motion_original PRIVATE AMReX::amrex_2d)
    if (AMReX_CUDA)
        setup_target_for_cuda_compilation(lbm3d_motion_original)
    endif ()
    add_executable(lbm3d_motion_modular Examples/Pitching_airfoil/marker_motion.cpp)
    target_include_directories(lbm3d_motion_modular PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Boundary/IBM
        ${CMAKE_CURRENT_SOURCE_DIR}/Source/Boundary)
    target_link_libraries(lbm3d_motion_modular PRIVATE AMReX::amrex_2d)
    if (AMReX_CUDA)
        setup_target_for_cuda_compilation(lbm3d_motion_modular)
    endif ()
    add_lbm_case(lbm3d_cavity ${CMAKE_CURRENT_SOURCE_DIR}/Examples/Cavity_flow)
    add_lbm_case(lbm3d_couette ${CMAKE_CURRENT_SOURCE_DIR}/Examples/Couette_flow)
    add_lbm_case(lbm3d_cylinder ${CMAKE_CURRENT_SOURCE_DIR}/Examples/Cylinder_flow)
    add_lbm_case(lbm3d_force_validation ${CMAKE_CURRENT_SOURCE_DIR}/Examples/ForceValidation)
    add_lbm_case(lbm3d_pitching_airfoil ${CMAKE_CURRENT_SOURCE_DIR}/Examples/Pitching_airfoil)
    add_lbm_case(lbm3d_taylor_green_2d ${CMAKE_CURRENT_SOURCE_DIR}/Examples/Taylor_Green_Vortex)
else ()
    add_lbm_case(lbm3d_sphere ${CMAKE_CURRENT_SOURCE_DIR}/Examples/Sphere_flow)
    add_lbm_case(lbm3d_square_duct ${CMAKE_CURRENT_SOURCE_DIR}/Examples/SquareDuct_flow)
    add_lbm_case(lbm3d_tgv3d
        ${CMAKE_CURRENT_SOURCE_DIR}/Benchmarks/TGV3D)
    add_executable(lbm3d_tgv3d_summary EXCLUDE_FROM_ALL
        Benchmarks/TGV3D/field_summary.cpp
        Examples/Common/ProblemInit.cpp)
    target_include_directories(lbm3d_tgv3d_summary PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/Benchmarks/TGV3D)
    target_link_libraries(lbm3d_tgv3d_summary PRIVATE lbm3d)
    if (AMReX_CUDA)
        setup_target_for_cuda_compilation(lbm3d_tgv3d_summary)
    endif ()
endif ()
