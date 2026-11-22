#include "AmrCoreLBM.H"
#include "DirectionalHalo.H"

#ifndef LBM_USE_IBM
#define LBM_USE_IBM 1
#endif

#include "Kernels.H"
#include <AMReX_FillPatchUtil.H>
#include <AMReX_PhysBCFunct.H>
#include <iomanip>

#if LBM_USE_IBM
#include "IBM/IBMarkerDF.H"
#include "LevelSet/LevelSet.H"
#endif


using namespace amrex;

void AmrCoreLBM::AdvancePhiAtLevel(int lev, Real time, Real dt_lev,
                                   int /*iteration*/, int /*ncycle*/) {
  // swap time slots
  std::swap(f_new[lev], f_old[lev]);
  std::swap(macro_new[lev], macro_old[lev]);

  MultiFab &sF_new = f_new[lev];
  MultiFab &sM_new = macro_new[lev];
  MultiFab *sForcingPtr = nullptr;

  if (m_use_cylinder && lev == finestLevel()) {
    if (forcing.size() > lev && forcing[lev].ok() &&
        forcing[lev].nComp() == 3) {
      sForcingPtr = &forcing[lev];
    }
  } else {
    // enforce "0 anywhere else"
    if (m_use_cylinder && forcing.size() > lev && forcing[lev].ok()) {
      forcing[lev].setVal(0.0);
    }
  }

  const bool use_force_fields =
      m_use_cylinder || m_use_prescribed_force || m_force_eval_debug > 0;
  std::unique_ptr<MultiFab> fx_cc;
  std::unique_ptr<MultiFab> fy_cc;
  std::unique_ptr<MultiFab> fz_cc;
  if (use_force_fields) {
    fx_cc = std::make_unique<MultiFab>(grids[lev], dmap[lev], 1, nghost);
    fy_cc = std::make_unique<MultiFab>(grids[lev], dmap[lev], 1, nghost);
    fz_cc = std::make_unique<MultiFab>(grids[lev], dmap[lev], 1, nghost);
    const auto force = m_use_prescribed_force
                           ? m_prescribed_force
                           : amrex::GpuArray<amrex::Real, 3>{0.0, 0.0, 0.0};
    fx_cc->setVal(force[0]);
    fy_cc->setVal(force[1]);
    fz_cc->setVal(force[2]);
  }
  MultiFab sfSborder(grids[lev], dmap[lev], sF_new.nComp(), sF_new.nGrow());
  const int ndir_l = ndir;
  if (lev > 0 || !geom[lev].isAllPeriodic()) {
    // Preserve old-time physical and coarse-fine ghosts without copying the
    // valid distribution field. Streaming reads only the first ghost layer.
    FillPatchMesoscopic(lev, time, f_old[lev], 0, f_old[lev].nComp());
    for (MFIter mfi(sfSborder, false); mfi.isValid(); ++mfi) {
      const Box &vbx = mfi.validbox();
      const Box gbx = mfi.growntilebox(1);
      auto const old = f_old[lev][mfi].const_array();
      auto const post = sfSborder[mfi].array();
      amrex::ParallelFor(
          gbx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
            if (!vbx.contains(i, j, k)) {
              for (int q = 0; q < ndir_l; ++q) {
                post(i, j, k, q) = old(i, j, k, q);
              }
            }
          });
    }
  }

#if LBM_USE_IBM
  std::unique_ptr<MultiFab> prevFxAlias;
  std::unique_ptr<MultiFab> prevFyAlias;
  std::unique_ptr<MultiFab> prevFzAlias;

  if (m_use_cylinder && lev == finestLevel()) {
    EnsureIBMBackend(lev, dmap[lev], grids[lev]);
  }

  // ---- Marker DF IBM (no level-set required; only on finest) ----
  if (lev == finestLevel() && m_ib_method == IBMMethodMarker && m_ibm) {
    // Marker interpolation needs current velocity ghosts. Fill them in the
    // old macro state without staging another full MultiFab.
    FillPatchMacro(lev, time, macro_old[lev], 0, 4);
    MultiFab rhocc(macro_old[lev], amrex::make_alias, 0, 1);
    MultiFab ucc(macro_old[lev], amrex::make_alias, 1, 1);
    MultiFab vcc(macro_old[lev], amrex::make_alias, 2, 1);
    MultiFab wcc(macro_old[lev], amrex::make_alias, 3, 1);
    if (sForcingPtr && sForcingPtr->nComp() >= 3) {
      prevFxAlias = std::make_unique<MultiFab>(*sForcingPtr, amrex::make_alias, 0, 1);
      prevFyAlias = std::make_unique<MultiFab>(*sForcingPtr, amrex::make_alias, 1, 1);
      prevFzAlias = std::make_unique<MultiFab>(*sForcingPtr, amrex::make_alias, 2, 1);
    }
    // IAMReX-style multi-direct-forcing with delta-kernel
    m_ibm->update_forcing(rhocc, ucc, vcc, wcc, *fx_cc, *fy_cc, *fz_cc, dt_lev,
                          time, prevFxAlias.get(), prevFyAlias.get(),
                          prevFzAlias.get());
  }
#endif // LBM_USE_IBM
  // amrex::Print() << "AdvancePhiAtLevel lev=" << lev
  //                << "  sF_new.nComp=" << sF_new.nComp()
  //                << "  sM_new.nComp=" << sM_new.nComp();

  // if (forcing.size() > lev) {
  //   amrex::Print() << "AdvancePhiAtLevel: lev=" << lev << " dt_lev=" <<
  //   dt_lev
  //                  << " forcing nComp=" << forcing[lev].nComp()
  //                  << " nGrow=" << forcing[lev].nGrow() << "\n";
  // }
  // amrex::Print() << "\n";

  // AMREX_ALWAYS_ASSERT_WITH_MESSAGE(
  //     sM_new.nComp() > 0 && sF_new.nComp() > 0,
  //     "macro_new[lev] or f_new[lev] has zero components!");

  // pack into forcing[lev] on valid region
  if (sForcingPtr) {
    MultiFab &sForcing = *sForcingPtr;
    for (MFIter mfi(sM_new, TilingIfNotGPU()); mfi.isValid(); ++mfi) {
      // amrex::Print() << "MFIter lev=" << lev
      //                << " sfSborder.nComp=" << sfSborder.nComp()
      //                << " box=" << mfi.validbox() << "\n";
      const Box &vbx = mfi.validbox();

      auto Fx = sForcing[mfi].array(0);
      auto Fy = sForcing[mfi].array(1);
      auto Fz = sForcing[mfi].array(2);

      auto fx = (*fx_cc)[mfi].const_array();
      auto fy = (*fy_cc)[mfi].const_array();
      auto fz = (*fz_cc)[mfi].const_array();

      amrex::ParallelFor(vbx,
                         [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
                           Fx(i, j, k) = fx(i, j, k, 0);
                           Fy(i, j, k) = fy(i, j, k, 0);
                           Fz(i, j, k) = fz(i, j, k, 0);
                           // amrex::Print() << "Packing forcing at i,j,k: " <<
                           // i << "," << j << ","
                           //                << k << " is " << Fx(i, j, k) <<
                           //                "," << Fy(i, j, k) <<
                           //                ","
                           //                << Fz(i, j, k) << "\n";
                         });
    }
  }

  if (m_force_eval_debug > 0) {
    // NOTE: `local=true` is per-rank and can print zero on IO rank even when
    // other ranks have nonzero forcing. Report both local and global norms.
    const Real maxFx_local = fx_cc->norm0(0, 0, true);
    const Real maxFy_local = fy_cc->norm0(0, 0, true);
    const Real maxFx_global = fx_cc->norm0(0, 0, false);
    const Real maxFy_global = fy_cc->norm0(0, 0, false);
    const Real maxF_global = std::max(maxFx_global, maxFy_global);

    Real maxFx_packed = Real(0.0);
    Real maxFy_packed = Real(0.0);
    if (sForcingPtr) {
      maxFx_packed = sForcingPtr->norm0(0, 0, false);
      maxFy_packed = sForcingPtr->norm0(1, 0, false);
    }
    const Real maxF_packed = std::max(maxFx_packed, maxFy_packed);

    amrex::Print() << std::scientific << std::setprecision(6)
                   << "[diag_force] lev=" << lev
                   << " step=" << (istep[lev] + 1)
                   << " t=" << time
                   << " cc_max|F|_global=" << maxF_global
                   << " (Fx=" << maxFx_global << ", Fy=" << maxFy_global << ")"
                   << " cc_max|F|_local=" << std::max(maxFx_local, maxFy_local)
                   << " packed_max|F|_global=" << maxF_packed
                   << " (Fx=" << maxFx_packed << ", Fy=" << maxFy_packed
                   << ")\n"
                   << std::defaultfloat;
  }

  const Real temptau = tau[lev];

  auto const *dirx_d = dirx_dev.data();
  auto const *diry_d = diry_dev.data();
  auto const *dirz_d = dirz_dev.data();
  auto const *wi_d = wi_dev.data();

#ifdef AMREX_USE_OMP
#pragma omp parallel if (Gpu::notInLaunchRegion())
#endif
  for (MFIter mfi(sF_new, false); mfi.isValid(); ++mfi) {
    const Box &vbx = mfi.validbox();

    Array4<Real const> rho_old = macro_old[lev][mfi].const_array(0);
    Array4<Real const> u_old = macro_old[lev][mfi].const_array(1);
    Array4<Real const> v_old = macro_old[lev][mfi].const_array(2);
    Array4<Real const> w_old = macro_old[lev][mfi].const_array(3);
    Array4<Real const> stateold = f_old[lev][mfi].const_array();
    Array4<Real> statepost = sfSborder[mfi].array();

    amrex::Array4<amrex::Real const> fx;
    amrex::Array4<amrex::Real const> fy;
    amrex::Array4<amrex::Real const> fz;
    if (use_force_fields) {
      fx = (*fx_cc)[mfi].const_array(0);
      fy = (*fy_cc)[mfi].const_array(0);
      fz = (*fz_cc)[mfi].const_array(0);
    }

    // Collide only on valid cells.
    // Distribution ghosts are synchronized from neighboring valid data below.
    amrex::ParallelFor(
        vbx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
          const amrex::Real rho_loc = rho_old(i, j, k);
          const amrex::Real u_loc = u_old(i, j, k);
          const amrex::Real v_loc = v_old(i, j, k);
          const amrex::Real w_loc = w_old(i, j, k);

          amrex::Real feq_loc[BCBuf::MAX_NDIR];
          for (int q = 0; q < ndir_l; ++q) {
            feq_loc[q] = feqFunction(wi_d[q], dirx_d[q], diry_d[q], dirz_d[q],
                                     rho_loc, u_loc, v_loc, w_loc);
          }

          const Real fx_loc = use_force_fields ? fx(i, j, k) : Real(0.0);
          const Real fy_loc = use_force_fields ? fy(i, j, k) : Real(0.0);
          const Real fz_loc = use_force_fields ? fz(i, j, k) : Real(0.0);
          collide_forced(i, j, k, stateold, statepost, feq_loc, ndir_l,
                         temptau, wi_d, dirx_d, diry_d, dirz_d, rho_loc,
                         u_loc, v_loc, w_loc, fx_loc, fy_loc, fz_loc);
        });
  }

  // Streaming reads only the nearest neighbor. Keep the wider FAB ghosts for
  // boundary and IBM operations.
  if (!m_directional_halo || !m_directional_halo->matches(sfSborder)) {
    m_directional_halo = std::make_unique<DirectionalHalo>(
        sfSborder, geom[lev], dirx, diry, dirz);
  }
  m_directional_halo->Fill(sfSborder);

#ifdef AMREX_USE_OMP
#pragma omp parallel if (Gpu::notInLaunchRegion())
#endif
  for (MFIter mfi(sF_new, false); mfi.isValid(); ++mfi) {
    const Box &vbx = mfi.validbox();
    Box gtbx = mfi.growntilebox(nghost); // clamped to FAB

    Array4<Real> statein = sfSborder[mfi].array();
    Array4<Real> stateout = sF_new[mfi].array();

    Array4<Real> rho = sM_new[mfi].array(0);
    Array4<Real> u = sM_new[mfi].array(1);
    Array4<Real> v = sM_new[mfi].array(2);
    Array4<Real> w = sM_new[mfi].array(3);

    amrex::Array4<amrex::Real const> fx;
    amrex::Array4<amrex::Real const> fy;
    amrex::Array4<amrex::Real const> fz;
    if (use_force_fields) {
      fx = (*fx_cc)[mfi].const_array(0);
      fy = (*fy_cc)[mfi].const_array(0);
      fz = (*fz_cc)[mfi].const_array(0);
    }

    const amrex::Box domain = geom[lev].Domain();
    const amrex::BCRec bc_rec =
        bcsMesoscopic.empty() ? amrex::BCRec() : bcsMesoscopic[0];

    // For `user_1` walls, impose stationary halfway bounce-back by populating
    // ghost cells with the fully reversed post-collision population from the
    // boundary-adjacent fluid cell that will pull from that ghost location.
    amrex::ParallelFor(
        gtbx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
          if (vbx.contains(i, j, k)) {
            return;
          }

          int flip_x = 0;
          int flip_y = 0;
          int flip_z = 0;
          bool has_bounce_back = false;
          bool unsupported_face = false;

          if (i < domain.smallEnd(0)) {
            if (bc_rec.lo(0) == amrex::BCType::user_1) {
              flip_x = 1;
              has_bounce_back = true;
            } else {
              unsupported_face = true;
            }
          } else if (i > domain.bigEnd(0)) {
            if (bc_rec.hi(0) == amrex::BCType::user_1) {
              flip_x = 1;
              has_bounce_back = true;
            } else {
              unsupported_face = true;
            }
          }

          if (j < domain.smallEnd(1)) {
            if (bc_rec.lo(1) == amrex::BCType::user_1) {
              flip_y = 1;
              has_bounce_back = true;
            } else {
              unsupported_face = true;
            }
          } else if (j > domain.bigEnd(1)) {
            if (bc_rec.hi(1) == amrex::BCType::user_1) {
              flip_y = 1;
              has_bounce_back = true;
            } else {
              unsupported_face = true;
            }
          }

          if (k < domain.smallEnd(2)) {
            if (bc_rec.lo(2) == amrex::BCType::user_1) {
              flip_z = 1;
              has_bounce_back = true;
            } else {
              unsupported_face = true;
            }
          } else if (k > domain.bigEnd(2)) {
            if (bc_rec.hi(2) == amrex::BCType::user_1) {
              flip_z = 1;
              has_bounce_back = true;
            } else {
              unsupported_face = true;
            }
          }

          if (!has_bounce_back || unsupported_face) {
            return;
          }

          for (int q = 0; q < ndir_l; ++q) {
            const int itgt = i + static_cast<int>(dirx_d[q]);
            const int jtgt = j + static_cast<int>(diry_d[q]);
            const int ktgt = k + static_cast<int>(dirz_d[q]);

            if (!vbx.contains(itgt, jtgt, ktgt)) {
              continue;
            }

            const int rx = -static_cast<int>(dirx_d[q]);
            const int ry = -static_cast<int>(diry_d[q]);
            const int rz = -static_cast<int>(dirz_d[q]);

            int q_reflect = q;
            for (int p = 0; p < ndir_l; ++p) {
              if (static_cast<int>(dirx_d[p]) == rx &&
                  static_cast<int>(diry_d[p]) == ry &&
                  static_cast<int>(dirz_d[p]) == rz) {
                q_reflect = p;
                break;
              }
            }

            statein(i, j, k, q) = statein(itgt, jtgt, ktgt, q_reflect);
          }
        });

    // -------- Stream --------
    amrex::ParallelFor(
        vbx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
          stream(i, j, k, stateout, statein, dirx_d, diry_d, dirz_d, ndir_l);
        });

    // -------- Macros w/ forcing + diagnostics --------
    amrex::ParallelFor(
        vbx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
          const Real fx_loc = use_force_fields ? fx(i, j, k) : Real(0.0);
          const Real fy_loc = use_force_fields ? fy(i, j, k) : Real(0.0);
          const Real fz_loc = use_force_fields ? fz(i, j, k) : Real(0.0);
          calculateMacroForcing(i, j, k, stateout, rho, u, v, w,
                                fx_loc, fy_loc, fz_loc, ndir_l,
                                dirx_d, diry_d, dirz_d);
        });
  }
  // The coarse level may be tagged for regridding on the next step.
  // Plot output refreshes derived fields in Evolve immediately before writing.
  if (lev < max_level && regrid_int > 0 &&
      ((istep[lev] + 1) % regrid_int) == 0) {
    UpdateDerivedMacroFields(lev, t_new[lev]);
  }

#ifdef AMREX_DEBUG
  {
    Real max_rho = macro_new[lev].norm0(0, 0, true);
    Real max_u = macro_new[lev].norm0(1, 0, true);
    Real max_v = macro_new[lev].norm0(2, 0, true);
    Real max_f = f_new[lev].norm0(0, 0, true); // component 0 is enough

    Real maxFx = 0.0;
    if (m_use_cylinder && forcing.size() > lev &&
        forcing[lev].boxArray().size() > 0) {
      maxFx = forcing[lev].norm0(0, 0, true);
    }

    if (amrex::ParallelDescriptor::IOProcessor()) {
      amrex::Print() << "[lev " << lev << "] diag: "
                     << "max rho=" << max_rho << " max |u| ~ "
                     << std::max(max_u, max_v) << " max f=" << max_f
                     << " max Fx=" << maxFx << "\n";
    }
  }
#endif
}
