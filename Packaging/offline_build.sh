#!/usr/bin/env bash
set -euo pipefail

bundle_dir=$(cd "$(dirname "$0")" && pwd)
cd "$bundle_dir"
sha256sum -c SHA256SUMS
mkdir -p work
tar -xzf project.tar.gz -C work
tar -xzf ilbmrex-upstream.tar.gz -C work
tar -xzf amrex-26.11-source.tar.gz -C work
tar -xzf cmake-3.30.9-linux-x86_64.tar.gz -C work

work_dir=$bundle_dir/work
cmake_bin=$work_dir/cmake-3.30.9-linux-x86_64/bin/cmake
amrex_src=$work_dir/lbm3d-amrex-26.11
project_src=$work_dir/LBM3D
cuda_compiler=${CMAKE_CUDA_COMPILER:-/usr/local/cuda/bin/nvcc}
cuda_arch=${LBM_CUDA_ARCH:-70}
{
    "$cuda_compiler" --version
    mpirun --version
    c++ --version
    python3 --version
    nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader
} > "$work_dir/toolchain.txt" 2>&1

for dim in 2 3; do
    "$cmake_bin" -S "$amrex_src" -B "$work_dir/amrex-build-${dim}d" \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_COMPILER="$cuda_compiler" \
        -DCMAKE_CUDA_ARCHITECTURES="$cuda_arch" \
        -DCMAKE_INSTALL_PREFIX="$work_dir/amrex-install-${dim}d" \
        -DAMReX_SPACEDIM="$dim" -DAMReX_GPU_BACKEND=CUDA \
        -DAMReX_PRECISION=DOUBLE -DAMReX_MPI=ON -DAMReX_PARTICLES=ON \
        -DAMReX_FORTRAN=OFF -DAMReX_CUDA_FASTMATH=OFF \
        > "$work_dir/amrex-config-${dim}d.log" 2>&1
    "$cmake_bin" --build "$work_dir/amrex-build-${dim}d" --parallel 4 \
        > "$work_dir/amrex-build-${dim}d.log" 2>&1
    "$cmake_bin" --install "$work_dir/amrex-build-${dim}d" \
        > "$work_dir/amrex-install-${dim}d.log" 2>&1
    "$cmake_bin" -S "$project_src" -B "$work_dir/lbm3d-build-${dim}d" \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_COMPILER="$cuda_compiler" \
        -DCMAKE_PREFIX_PATH="$work_dir/amrex-install-${dim}d" \
        -DLBM_DIM="$dim" \
        > "$work_dir/lbm3d-config-${dim}d.log" 2>&1
    "$cmake_bin" --build "$work_dir/lbm3d-build-${dim}d" --parallel 4 \
        > "$work_dir/lbm3d-build-${dim}d.log" 2>&1
done

mkdir -p "$work_dir/smoke"
cd "$work_dir/smoke"
CUDA_VISIBLE_DEVICES=0 "$work_dir/lbm3d-build-3d/lbm3d_tgv3d" \
    "$project_src/Benchmarks/TGV3D/inputs_physics_64" \
    max_step=2 amr.plot_int=-1 amr.chk_int=-1 \
    > "$work_dir/smoke.log" 2>&1
grep 'Coarse STEP 2 ends' "$work_dir/smoke.log"
grep 'finalized' "$work_dir/smoke.log"

if [[ ${1:-} == --full ]]; then
    "$cmake_bin" -S "$project_src/Baseline" -B "$work_dir/baseline-build-3d" \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_COMPILER="$cuda_compiler" \
        -DCMAKE_PREFIX_PATH="$work_dir/amrex-install-3d" \
        -DLBM_DIM=3 -DLBM_CASE=TGV3D \
        > "$work_dir/baseline-config-3d.log" 2>&1
    "$cmake_bin" --build "$work_dir/baseline-build-3d" --parallel 4 \
        > "$work_dir/baseline-build-3d.log" 2>&1
    "$cmake_bin" -S "$project_src/Baseline" -B "$work_dir/baseline-timed-3d" \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_COMPILER="$cuda_compiler" \
        -DCMAKE_PREFIX_PATH="$work_dir/amrex-install-3d" \
        -DLBM_DIM=3 -DLBM_CASE=TGV3D -DLBM_BASELINE_TIMING=ON \
        > "$work_dir/baseline-timed-config-3d.log" 2>&1
    "$cmake_bin" --build "$work_dir/baseline-timed-3d" --target ilbmrex_baseline --parallel 4 \
        > "$work_dir/baseline-timed-build-3d.log" 2>&1
    for timing in OFF ON; do
        build_dir=$work_dir/lbm3d-analysis-${timing}
        "$cmake_bin" -S "$project_src" -B "$build_dir" \
            -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_COMPILER="$cuda_compiler" \
            -DCMAKE_PREFIX_PATH="$work_dir/amrex-install-3d" \
            -DLBM_DIM=3 -DLBM_ENABLE_IBM=OFF -DLBM_TIMING="$timing" \
            > "$work_dir/lbm3d-analysis-${timing}-config.log" 2>&1
        "$cmake_bin" --build "$build_dir" --target lbm3d_tgv3d --parallel 4 \
            > "$work_dir/lbm3d-analysis-${timing}-build.log" 2>&1
    done
    source_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project_commit"])' "$bundle_dir/manifest.json")
    python3 "$project_src/Benchmarks/TGV3D/run_p1.py" \
        --baseline "$work_dir/baseline-build-3d/ilbmrex_baseline" \
        --baseline-timed "$work_dir/baseline-timed-3d/ilbmrex_baseline" \
        --modular "$work_dir/lbm3d-analysis-OFF/lbm3d_tgv3d" \
        --modular-timed "$work_dir/lbm3d-analysis-ON/lbm3d_tgv3d" \
        --analyzer "$work_dir/baseline-build-3d/tgv3d_analyze" \
        --comparator "$work_dir/lbm3d-build-3d/lbm_compare" \
        --source-version "$source_version" \
        --work "$work_dir/full-p1" \
        > "$work_dir/full-p1.log" 2>&1
    tail -3 "$work_dir/full-p1.log"
fi
