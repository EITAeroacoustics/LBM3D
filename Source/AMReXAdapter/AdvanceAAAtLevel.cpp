#include "AmrCoreLBM.H"
#include "DirectionalHalo.H"

#include <AMReX_Math.H>
#include <AMReX_ParReduce.H>
#include <AMReX_ParallelContext.H>
#include <AMReX_ParallelDescriptor.H>
#include <AMReX_Print.H>

#include <feq.H>

#include <iomanip>
#include <limits>

using namespace amrex;

// AA stores alternate time levels in two interpretations of the same f FAB.
// Even steps reverse each local population; odd steps gather the reversed
// populations, then scatter collision results to their neighboring locations.
void AmrCoreLBM::AdvanceAAAtLevel(int lev) {
  AMREX_ALWAYS_ASSERT(lev == 0 && m_aa_storage);
  MultiFab& f = f_new[lev];
  MultiFab& macro = macro_new[lev];
  bool const even = !m_aa_flipped;
  Real const tau_lev = tau[lev];
  auto const* wi_d = wi_dev.data();
  auto const* cx_d = dirx_dev.data();
  auto const* cy_d = diry_dev.data();
  auto const* cz_d = dirz_dev.data();
  auto const opposite = m_aa_opposite;

  for (MFIter mfi(f, TilingIfNotGPU()); mfi.isValid(); ++mfi) {
    Box const& bx = mfi.validbox();
    auto const state = f[mfi].array();
    auto const rho = macro[mfi].const_array(0);
    auto const u = macro[mfi].const_array(1);
    auto const v = macro[mfi].const_array(2);
    auto const w = macro[mfi].const_array(3);
    if (even) {
      ParallelFor(bx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
        Real incoming[19];
        for (int q = 0; q < 19; ++q) {
          incoming[q] = state(i, j, k, q);
        }
        Real const r = rho(i, j, k);
        Real const ux = u(i, j, k);
        Real const uy = v(i, j, k);
        Real const uz = w(i, j, k);
        for (int q = 0; q < 19; ++q) {
          Real const equilibrium = feqFunction(
              wi_d[q], cx_d[q], cy_d[q], cz_d[q], r, ux, uy, uz);
          state(i, j, k, opposite[q]) =
              Real(1.0) * incoming[q] - (incoming[q] - equilibrium) / tau_lev;
        }
      });
    } else {
      ParallelFor(bx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
        Real incoming[19];
        for (int q = 0; q < 19; ++q) {
          int const sx = static_cast<int>(cx_d[q]);
          int const sy = static_cast<int>(cy_d[q]);
          int const sz = static_cast<int>(cz_d[q]);
          incoming[q] = state(i - sx, j - sy, k - sz, opposite[q]);
        }
        Real const r = rho(i, j, k);
        Real const ux = u(i, j, k);
        Real const uy = v(i, j, k);
        Real const uz = w(i, j, k);
        for (int q = 0; q < 19; ++q) {
          Real const equilibrium = feqFunction(
              wi_d[q], cx_d[q], cy_d[q], cz_d[q], r, ux, uy, uz);
          int const sx = static_cast<int>(cx_d[q]);
          int const sy = static_cast<int>(cy_d[q]);
          int const sz = static_cast<int>(cz_d[q]);
          state(i + sx, j + sy, k + sz, q) =
              Real(1.0) * incoming[q] - (incoming[q] - equilibrium) / tau_lev;
        }
      });
    }
  }

  if (!m_directional_halo || !m_directional_halo->matches(f, true)) {
    m_directional_halo = std::make_unique<DirectionalHalo>(
        f, geom[lev], dirx, diry, dirz, true);
  }
  // Multiple remote peers leave enough receive time to hide the interior
  // macro update; a single peer does not offset the extra boundary launch.
  bool const overlap_macro = m_directional_halo->hasMultipleIncomingPeers(!even);
  bool const flipped = even;
  if (!overlap_macro) {
    if (even) {
      m_directional_halo->Fill(f);
    } else {
      m_directional_halo->ScatterAA(f);
    }
    for (MFIter mfi(macro, TilingIfNotGPU()); mfi.isValid(); ++mfi) {
      Box const& bx = mfi.validbox();
      auto const state = f[mfi].const_array();
      auto const rho = macro[mfi].array(0);
      auto const u = macro[mfi].array(1);
      auto const v = macro[mfi].array(2);
      auto const w = macro[mfi].array(3);
      ParallelFor(bx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
        Real r = 0.0, m1 = 0.0, m2 = 0.0, m3 = 0.0;
        for (int q = 0; q < 19; ++q) {
          Real fq;
          if (flipped) {
            int const sx = static_cast<int>(cx_d[q]);
            int const sy = static_cast<int>(cy_d[q]);
            int const sz = static_cast<int>(cz_d[q]);
            fq = state(i - sx, j - sy, k - sz, opposite[q]);
          } else {
            fq = state(i, j, k, q);
          }
          r += fq;
          m1 += cx_d[q] * fq;
          m2 += cy_d[q] * fq;
          m3 += cz_d[q] * fq;
        }
        rho(i, j, k) = r;
        u(i, j, k) = (m1 + Real(0.5) * Real(0.0)) / r;
        v(i, j, k) = (m2 + Real(0.5) * Real(0.0)) / r;
        w(i, j, k) = (m3 + Real(0.5) * Real(0.0)) / r;
      });
    }
    m_aa_flipped = flipped;
    return;
  }
  auto update_macro = [&](bool interior) {
    MFItInfo mfi_info;
    if (interior) { mfi_info.DisableDeviceSync(); }
    for (MFIter mfi(macro, mfi_info); mfi.isValid(); ++mfi) {
      Box const& bx = mfi.validbox();
      auto const state = f[mfi].const_array();
      auto const rho = macro[mfi].array(0);
      auto const u = macro[mfi].array(1);
      auto const v = macro[mfi].array(2);
      auto const w = macro[mfi].array(3);
      auto const calculate = [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
        Real r = 0.0, m1 = 0.0, m2 = 0.0, m3 = 0.0;
        for (int q = 0; q < 19; ++q) {
          Real fq;
          if (flipped) {
            int const sx = static_cast<int>(cx_d[q]);
            int const sy = static_cast<int>(cy_d[q]);
            int const sz = static_cast<int>(cz_d[q]);
            fq = state(i - sx, j - sy, k - sz, opposite[q]);
          } else {
            fq = state(i, j, k, q);
          }
          r += fq;
          m1 += cx_d[q] * fq;
          m2 += cy_d[q] * fq;
          m3 += cz_d[q] * fq;
        }
        rho(i, j, k) = r;
        u(i, j, k) = (m1 + Real(0.5) * Real(0.0)) / r;
        v(i, j, k) = (m2 + Real(0.5) * Real(0.0)) / r;
        w(i, j, k) = (m3 + Real(0.5) * Real(0.0)) / r;
      };
      Box inner = bx;
      inner.grow(-1);
      if (interior) {
        if (inner.ok()) { ParallelFor(inner, calculate); }
      } else if (inner.ok()) {
        Box xlo = bx;
        xlo.setBig(0, bx.smallEnd(0));
        Box xhi = bx;
        xhi.setSmall(0, bx.bigEnd(0));
        Box ylo = bx;
        ylo.setSmall(0, inner.smallEnd(0));
        ylo.setBig(0, inner.bigEnd(0));
        ylo.setBig(1, bx.smallEnd(1));
        Box yhi = bx;
        yhi.setSmall(0, inner.smallEnd(0));
        yhi.setBig(0, inner.bigEnd(0));
        yhi.setSmall(1, bx.bigEnd(1));
        Box zlo = inner;
        zlo.setSmall(2, bx.smallEnd(2));
        zlo.setBig(2, bx.smallEnd(2));
        Box zhi = inner;
        zhi.setSmall(2, bx.bigEnd(2));
        zhi.setBig(2, bx.bigEnd(2));
        Long const end_xlo = xlo.numPts();
        Long const end_xhi = end_xlo + xhi.numPts();
        Long const end_ylo = end_xhi + ylo.numPts();
        Long const end_yhi = end_ylo + yhi.numPts();
        Long const end_zlo = end_yhi + zlo.numPts();
        Long const end_zhi = end_zlo + zhi.numPts();
        ParallelFor(end_zhi, [=] AMREX_GPU_DEVICE(Long index) noexcept {
          GpuArray<int, 3> cell;
          if (index < end_xlo) {
            cell = xlo.atOffset3d(index);
          } else if (index < end_xhi) {
            cell = xhi.atOffset3d(index - end_xlo);
          } else if (index < end_ylo) {
            cell = ylo.atOffset3d(index - end_xhi);
          } else if (index < end_yhi) {
            cell = yhi.atOffset3d(index - end_ylo);
          } else if (index < end_zlo) {
            cell = zlo.atOffset3d(index - end_yhi);
          } else {
            cell = zhi.atOffset3d(index - end_zlo);
          }
          calculate(cell[0], cell[1], cell[2]);
        });
      } else {
        ParallelFor(bx, calculate);
      }
    }
  };
  auto before_wait = [&] { update_macro(true); };
  if (even) {
    m_directional_halo->Fill(f, before_wait);
  } else {
    m_directional_halo->ScatterAA(f, before_wait);
  }
  update_macro(false);
  m_aa_flipped = flipped;
}

void AmrCoreLBM::PrintAATgvMetrics(int step, Real time) const {
  MultiFab const& f = f_new[0];
  MultiFab const& macro = macro_new[0];
  auto const populations = f.const_arrays();
  auto const moments = macro.const_arrays();
  auto const* cx_d = dirx_dev.data();
  auto const* cy_d = diry_dev.data();
  auto const* cz_d = dirz_dev.data();
  auto const opposite = m_aa_opposite;
  bool const flipped = m_aa_flipped;
  auto const reduced = ParReduce(
      TypeList<ReduceOpSum, ReduceOpSum, ReduceOpMin, ReduceOpMin,
               ReduceOpSum>{},
      TypeList<Real, Real, Real, Real, unsigned long long>{},
      f, IntVect(0),
      [=] AMREX_GPU_DEVICE(int box, int i, int j, int k) noexcept
          -> GpuTuple<Real, Real, Real, Real, unsigned long long> {
        Real const r = moments[box](i, j, k, 0);
        Real const ux = moments[box](i, j, k, 1);
        Real const uy = moments[box](i, j, k, 2);
        Real const uz = moments[box](i, j, k, 3);
        unsigned long long bad =
            !(Math::isfinite(r) && Math::isfinite(ux) &&
              Math::isfinite(uy) && Math::isfinite(uz));
        Real min_f = std::numeric_limits<Real>::max();
        for (int q = 0; q < 19; ++q) {
          Real fq;
          if (flipped) {
            int const sx = static_cast<int>(cx_d[q]);
            int const sy = static_cast<int>(cy_d[q]);
            int const sz = static_cast<int>(cz_d[q]);
            fq = populations[box](i - sx, j - sy, k - sz, opposite[q]);
          } else {
            fq = populations[box](i, j, k, q);
          }
          if (Math::isfinite(fq)) {
            min_f = amrex::min(min_f, fq);
          } else {
            ++bad;
          }
        }
        Real const mass = Math::isfinite(r) ? r : Real(0.0);
        Real const kinetic = bad == 0
            ? Real(0.5) * r * (ux * ux + uy * uy + uz * uz)
            : Real(0.0);
        Real const min_rho = Math::isfinite(r)
            ? r : std::numeric_limits<Real>::max();
        return {mass, kinetic, min_rho, min_f, bad};
      });
  Real sums[2] = {get<0>(reduced), get<1>(reduced)};
  Real minimums[2] = {get<2>(reduced), get<3>(reduced)};
  unsigned long long nonfinite = get<4>(reduced);
#ifdef AMREX_USE_MPI
  MPI_Comm const comm = ParallelContext::CommunicatorSub();
  auto const real_type = ParallelDescriptor::Mpi_typemap<Real>::type();
  BL_MPI_REQUIRE(MPI_Allreduce(MPI_IN_PLACE, sums, 2, real_type,
                               MPI_SUM, comm));
  BL_MPI_REQUIRE(MPI_Allreduce(MPI_IN_PLACE, minimums, 2, real_type,
                               MPI_MIN, comm));
  BL_MPI_REQUIRE(MPI_Allreduce(MPI_IN_PLACE, &nonfinite, 1,
                               MPI_UNSIGNED_LONG_LONG, MPI_SUM, comm));
#endif
  Real const cells = static_cast<Real>(geom[0].Domain().numPts());
  Print() << std::setprecision(17)
          << "TGV_METRICS step=" << step << " time=" << time
          << " cells=" << geom[0].Domain().numPts()
          << " mean_rho=" << sums[0] / cells
          << " mean_kinetic=" << sums[1] / cells
          << " nonfinite=" << nonfinite
          << " min_rho=" << minimums[0]
          << " min_f=" << minimums[1] << '\n';
  AMREX_ALWAYS_ASSERT_WITH_MESSAGE(
      nonfinite == 0 && minimums[0] > Real(0.0) && minimums[1] > Real(0.0),
      "AA TGV has a nonfinite or nonpositive density or population.");
}
