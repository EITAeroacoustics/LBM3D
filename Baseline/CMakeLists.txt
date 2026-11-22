cmake_minimum_required(VERSION 3.25)

project(iLBMReXBaseline LANGUAGES CXX)

set(LBM_CASE "TGV3D" CACHE STRING "3D baseline case: TGV3D, Sphere_flow or SquareDuct_flow")
option(LBM_BASELINE_TIMING "Instrument steps 101-600 in a build-local core copy" OFF)
option(LBM_BASELINE_IBM "Enable the original IBM coupling for IBM regression cases" OFF)

find_package(AMReX REQUIRED)
if (NOT TARGET AMReX::amrex_3d)
    message(FATAL_ERROR "The baseline requires a 3D AMReX installation")
endif ()
if (NOT AMReX_CUDA)
    message(FATAL_ERROR "The baseline requires AMReX with CUDA")
endif ()

set(lbm_source_dir "${CMAKE_CURRENT_LIST_DIR}/../iLBMReX/Source")
# AMReX 26.11 defines AMREX_PARTICLES without a numeric value. The upstream
# IBM sources test it as a number; adjust only those preprocessor lines in
# build-local copies. The original iLBMReX source tree is untouched.
file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/compat/IBM")
foreach (ibm_file IBMarkerDF.H IBMarkerDF.cpp)
    file(READ "${lbm_source_dir}/IBM/${ibm_file}" ibm_text)
    string(REPLACE "#if defined(AMREX_PARTICLES) && AMREX_PARTICLES"
        "#ifdef AMREX_PARTICLES" ibm_text "${ibm_text}")
    file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/compat/IBM/${ibm_file}" "${ibm_text}")
endforeach ()
set(lbm_core_file "${lbm_source_dir}/Core/AmrCoreLBM.cpp")
if (LBM_BASELINE_TIMING)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    set(lbm_core_file "${CMAKE_CURRENT_BINARY_DIR}/compat/AmrCoreLBM.cpp")
    execute_process(
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/make_timed_core.py"
                "${lbm_source_dir}/Core/AmrCoreLBM.cpp" "${lbm_core_file}"
        COMMAND_ERROR_IS_FATAL ANY)
endif ()
if (LBM_CASE STREQUAL "TGV3D")
    set(lbm_case_dir "${CMAKE_CURRENT_LIST_DIR}/../Benchmarks/TGV3D")
elseif (LBM_CASE STREQUAL "Sphere_flow" OR LBM_CASE STREQUAL "SquareDuct_flow")
    set(lbm_case_dir "${CMAKE_CURRENT_LIST_DIR}/../iLBMReX/Examples/${LBM_CASE}")
else ()
    message(FATAL_ERROR "LBM_CASE must be TGV3D, Sphere_flow or SquareDuct_flow")
endif ()
if (NOT EXISTS "${lbm_case_dir}/Prob.H")
    message(FATAL_ERROR "Missing case initial field: ${lbm_case_dir}/Prob.H")
endif ()

add_executable(ilbmrex_baseline
    "${lbm_source_dir}/main.cpp"
    "${lbm_source_dir}/BC/bc_val.cpp"
    "${lbm_source_dir}/Core/AdvanceLBMAtLevel.cpp"
    "${lbm_core_file}"
    "${CMAKE_CURRENT_BINARY_DIR}/compat/IBM/IBMarkerDF.cpp"
    "${lbm_source_dir}/IBM/IBForceEval.cpp"
    "${lbm_source_dir}/LevelSet/LevelSet.cpp")

target_include_directories(ilbmrex_baseline PRIVATE
    "${CMAKE_CURRENT_BINARY_DIR}/compat"
    "${lbm_case_dir}"
    "${lbm_source_dir}"
    "${lbm_source_dir}/BC"
    "${lbm_source_dir}/Core"
    "${lbm_source_dir}/IBM"
    "${lbm_source_dir}/LBM"
    "${lbm_source_dir}/LevelSet"
    "${lbm_source_dir}/Utils")
if (LBM_BASELINE_IBM)
    target_compile_definitions(ilbmrex_baseline PRIVATE LBM_USE_IBM=1)
else ()
    target_compile_definitions(ilbmrex_baseline PRIVATE LBM_USE_IBM=0)
endif ()
target_link_libraries(ilbmrex_baseline PRIVATE AMReX::amrex_3d)

enable_language(CUDA)
include(AMReXTargetHelpers)
setup_target_for_cuda_compilation(ilbmrex_baseline)

if (LBM_CASE STREQUAL "TGV3D")
    add_executable(tgv3d_analyze "${lbm_case_dir}/analyze.cpp")
    target_link_libraries(tgv3d_analyze PRIVATE AMReX::amrex_3d)
    add_executable(tgv3d_compare "${lbm_case_dir}/compare.cpp")
    target_link_libraries(tgv3d_compare PRIVATE AMReX::amrex_3d)
    setup_target_for_cuda_compilation(tgv3d_analyze)
    setup_target_for_cuda_compilation(tgv3d_compare)
endif ()
