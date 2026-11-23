#include <ProblemInit.H>
#include <Prob.H>

#include <AMReX_GpuLaunch.H>
#include <AMReX_MFIter.H>

void InitializeProblem(amrex::MultiFab& macro, amrex::Geometry const& geom,
                       amrex::Real nu)
{
    AMREX_ALWAYS_ASSERT(macro.nComp() >= 4);
    const auto problo = geom.ProbLoArray();
    const auto probhi = geom.ProbHiArray();
    const auto dx = geom.CellSizeArray();
    const int ncomp = macro.nComp();

#ifdef AMREX_USE_OMP
#pragma omp parallel if (amrex::Gpu::notInLaunchRegion())
#endif
    for (amrex::MFIter mfi(macro, amrex::TilingIfNotGPU()); mfi.isValid(); ++mfi) {
        auto rho = macro[mfi].array(0);
        auto u = macro[mfi].array(1);
        auto v = macro[mfi].array(2);
        auto w = macro[mfi].array(3);
        auto all = macro[mfi].array();
        const auto& box = mfi.fabbox();

        amrex::ParallelFor(box, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
            initdata(i, j, k, rho, u, v, w, problo, probhi, dx, nu);
            for (int comp = 4; comp < ncomp; ++comp) {
                all(i, j, k, comp) = 0.0;
            }
        });
    }
}
