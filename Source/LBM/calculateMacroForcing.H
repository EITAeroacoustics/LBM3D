#ifndef CALCULATE_MACRO_FORCING_H_
#define CALCULATE_MACRO_FORCING_H_

#include <AMReX_Box.H>
#include <AMReX_FArrayBox.H>

AMREX_GPU_DEVICE
AMREX_FORCE_INLINE
void calculateMacroForcing(int i, int j, int k,
                           amrex::Array4<amrex::Real const> const &f_arr,
                           amrex::Array4<amrex::Real> const &rho,
                           amrex::Array4<amrex::Real> const &u,
                           amrex::Array4<amrex::Real> const &v,
                           amrex::Array4<amrex::Real> const &w,
                           amrex::Real fx, amrex::Real fy, amrex::Real fz,
                           int ndir,
                           amrex::Real const *dirx, amrex::Real const *diry,
                           amrex::Real const *dirz) {
  amrex::Real r = 0, m1 = 0, m2 = 0, m3 = 0;
  for (int q = 0; q < ndir; ++q) {
    amrex::Real fq = f_arr(i, j, k, q);
    r += fq;
    m1 += dirx[q] * fq;
    m2 += diry[q] * fq;
    m3 += dirz[q] * fq;
  }
  rho(i, j, k) = r;
  u(i, j, k) = (m1 + 0.5 * fx) / r;
  v(i, j, k) = (m2 + 0.5 * fy) / r;
  w(i, j, k) = (m3 + 0.5 * fz) / r;
}

#endif
