#include <ProblemInit.H>
#include <Prob.H>

#include <AMReX_GpuLaunch.H>
#include <AMReX_MFIter.H>

// This translation unit is compiled once per example. Prob.H therefore stays
// in the example target, while the linked LBM3D library is case-independent.
void InitializeProblem(amrex::MultiFab& macro, amrex::Geometry const& geom,
                       amrex::Real nu)
{
    const auto problo = geom.ProbLoArray();
    const auto probhi = geom.ProbHiArray();
    const auto dx = geom.CellSizeArray();

#ifdef AMREX_USE_OMP
#pragma omp parallel if (amrex::Gpu::notInLaunchRegion())
#endif
    for (amrex::MFIter mfi(macro, amrex::TilingIfNotGPU()); mfi.isValid(); ++mfi) {
        auto rho = macro[mfi].array(0);
        auto u = macro[mfi].array(1);
        auto v = macro[mfi].array(2);
        auto w = macro[mfi].array(3);
        auto vor = macro[mfi].array(4);
        const auto& box = mfi.fabbox();

        amrex::ParallelFor(box, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
            initdata(i, j, k, rho, u, v, w, vor, problo, probhi, dx, nu);
        });
    }
}
