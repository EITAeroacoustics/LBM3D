#ifndef LBM3D_TGV3D_PROB_H_
#define LBM3D_TGV3D_PROB_H_

#include <AMReX_Array4.H>
#include <AMReX_Geometry.H>
#include <AMReX_Math.H>

static_assert(AMREX_SPACEDIM == 3, "TGV3D requires a 3D AMReX build");

// Standard three-dimensional Taylor-Green initial field on a periodic cube.
// U0 is fixed for this benchmark; grid size and MPI decomposition come from
// the input file and launch command.
AMREX_GPU_DEVICE AMREX_FORCE_INLINE
void initdata(int i, int j, int k,
              amrex::Array4<amrex::Real> const& rho,
              amrex::Array4<amrex::Real> const& ux,
              amrex::Array4<amrex::Real> const& uy,
              amrex::Array4<amrex::Real> const& uz,
              amrex::GpuArray<amrex::Real, AMREX_SPACEDIM> const& prob_lo,
              amrex::GpuArray<amrex::Real, AMREX_SPACEDIM> const& prob_hi,
              amrex::GpuArray<amrex::Real, AMREX_SPACEDIM> const& dx,
              double nu)
{
    amrex::ignore_unused(nu);

    constexpr amrex::Real rho0 = 1.0;
    constexpr amrex::Real u0 = 0.02;
    constexpr amrex::Real cs2 = 1.0 / 3.0;
    const amrex::Real two_pi = 2.0 * amrex::Math::pi<amrex::Real>();
    const amrex::Real kx = two_pi / (prob_hi[0] - prob_lo[0]);
    const amrex::Real ky = two_pi / (prob_hi[1] - prob_lo[1]);
    const amrex::Real kz = two_pi / (prob_hi[2] - prob_lo[2]);

    const amrex::Real x = prob_lo[0] + (i + 0.5) * dx[0];
    const amrex::Real y = prob_lo[1] + (j + 0.5) * dx[1];
    const amrex::Real z = prob_lo[2] + (k + 0.5) * dx[2];
    const auto sx = amrex::Math::sincos(kx * x);
    const auto sy = amrex::Math::sincos(ky * y);
    const auto sz = amrex::Math::sincos(kz * z);

    ux(i, j, k) =  u0 * sx.first * sy.second * sz.second;
    uy(i, j, k) = -u0 * sx.second * sy.first * sz.second;
    uz(i, j, k) = 0.0;

    const amrex::Real pressure =
        rho0 * u0 * u0 / 16.0 *
        (amrex::Math::sincos(2.0 * kx * x).second +
         amrex::Math::sincos(2.0 * ky * y).second) *
        (amrex::Math::sincos(2.0 * kz * z).second + 2.0);
    rho(i, j, k) = rho0 + pressure / cs2;
}

#endif
