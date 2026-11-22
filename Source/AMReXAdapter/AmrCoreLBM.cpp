
#include <AMReX_FillPatchUtil.H>
#include "DirectionalHalo.H"
#include <AMReX_MultiFabUtil.H>
#include <AMReX_ParallelDescriptor.H>
#include <AMReX_ParmParse.H>
#include <AMReX_PhysBCFunct.H>

#ifdef AMREX_MEM_PROFILING
#include <AMReX_MemProfiler.H>
#endif

#include <AmrCoreLBM.H>
#include <Kernels.H>

#include "DebugNaN.H"

#include "IBM/IBMarkerDF.H"
#include "IBM/IBForceEval.H"
#include "LevelSet/LevelSet.H"
#include <AMReX_GpuContainers.H>

#include <iomanip> // optional, for nicer formatting

#include "IBM/PitchingAirfoilGeometry.H"

namespace {

inline amrex::Real ib_refine_padding(amrex::Real dx) noexcept {
  return amrex::max(amrex::Real(6.0) * dx, amrex::Real(2.0));
}

inline bool immersed_boundary_refinement_region(
    amrex::Real x0, amrex::Real y0, amrex::Real z0, amrex::Real radius,
    MarkerIBParams const &par, amrex::Real dx, amrex::Real &xlo,
    amrex::Real &xhi, amrex::Real &ylo, amrex::Real &yhi, amrex::Real &zlo,
    amrex::Real &zhi) noexcept {
  const amrex::Real pad = ib_refine_padding(dx);

  if (par.geometry_type == MarkerIBParams::GeometryBox) {
    xlo = par.box_xlo - pad;
    xhi = par.box_xhi + pad;
    ylo = (par.box_lid_only > 0) ? (par.box_yhi - pad) : (par.box_ylo - pad);
    yhi = par.box_yhi + pad;
    zlo = par.box_zlo - pad;
    zhi = par.box_zhi + pad;
    return true;
  }

  if (par.geometry_type == MarkerIBParams::GeometryUserDefined) {
    return lbm_user_ibm_geometry::refinement_region(
        x0, y0, z0, par, dx, xlo, xhi, ylo, yhi, zlo, zhi);
  }

  if (radius > amrex::Real(0.0)) {
    if (par.refine_upstream > amrex::Real(0.0) &&
        par.refine_downstream > amrex::Real(0.0) &&
        par.refine_cross > amrex::Real(0.0)) {
      xlo = x0 - par.refine_upstream * radius - pad;
      xhi = x0 + par.refine_downstream * radius + pad;
      ylo = y0 - par.refine_cross * radius - pad;
      yhi = y0 + par.refine_cross * radius + pad;
      zlo = z0 - par.refine_cross * radius - pad;
      zhi = z0 + par.refine_cross * radius + pad;
    } else {
      xlo = x0 - radius - pad;
      xhi = x0 + radius + pad;
      ylo = y0 - radius - pad;
      yhi = y0 + radius + pad;
      zlo = z0 - radius - pad;
      zhi = z0 + radius + pad;
    }
    return true;
  }

  return false;
}

void update_derived_macro_fields_impl(amrex::MultiFab &curMacro,
                                      amrex::MultiFab const &macro_patch,
                                      amrex::Real dx, amrex::Real dy,
                                      amrex::Real dz,
                                      amrex::Real T0_local) {
#ifdef AMREX_USE_OMP
#pragma omp parallel if (amrex::Gpu::notInLaunchRegion())
#endif
  for (amrex::MFIter mfi(macro_patch, amrex::TilingIfNotGPU()); mfi.isValid();
       ++mfi) {
    const amrex::Box &vbx = mfi.validbox();
    const int K = mfi.index();

    auto const rho = macro_patch[K].array(0);
    auto const u = macro_patch[K].array(1);
    auto const v = macro_patch[K].array(2);
    auto const w = macro_patch[K].array(3);

    auto const vor = curMacro[K].array(4);
    auto const P = curMacro[K].array(5);

    amrex::ParallelFor(vbx, [=] AMREX_GPU_DEVICE(int i, int j,
                                                 int k) noexcept {
      visPara(i, j, k, rho, u, v, w, vor, P, dx, dy, dz, T0_local);
    });
  }
}

} // namespace

using namespace amrex;

void AmrCoreLBM::ResetIBMBackend() {
  m_ibm.reset();
  m_ibm_level = -1;
}

void AmrCoreLBM::ResetForceHistory() {
  if (m_force_ofs.is_open()) {
    m_force_ofs.close();
  }
  m_force_output_initialized = false;
  m_have_prev_body_force = false;
  m_prev_body_force = {amrex::Real(0.0), amrex::Real(0.0), amrex::Real(0.0)};
}

void AmrCoreLBM::UpdateDerivedMacroFields(int lev, Real time) {
  constexpr int derive_ncomp = 4; // rho, ux, uy, uz(dummy in 2D)
  MultiFab macro_patch(grids[lev], dmap[lev], derive_ncomp, 1);
  FillPatchMacro(lev, time, macro_patch, 0, derive_ncomp);

  MultiFab &curMacro = macro_new[lev];
  const Real tempdx = xCellSize[lev];
  const Real tempdy = yCellSize[lev];
#if (AMREX_SPACEDIM == 3)
  const Real tempdz = zCellSize[lev];
#else
  const Real tempdz = Real(0.0);
#endif
  const Real T0_local = T0;
  update_derived_macro_fields_impl(curMacro, macro_patch, tempdx, tempdy,
                                   tempdz, T0_local);
}

void AmrCoreLBM::EnsureIBMBackend(int lev, DistributionMapping const &dm,
                                  BoxArray const &ba) {
  if (m_ib_method != IBMMethodMarker) {
    ResetIBMBackend();
    return;
  }

  if (!m_ibm || m_ibm_level != lev) {
    m_ibm = std::make_unique<IBMarkerDF>(geom[lev], dm, ba, m_ls_par.x0,
                                         m_ls_par.y0, m_ls_par.z0, m_ls_par.R,
                                         m_marker_par);
    m_ibm_level = lev;
    amrex::Print() << "Initialized marker IBM backend on level " << lev
                   << "\n";
  }
}

// constructor - reads in parameters from inputs file
//             - sizes multilevel arrays and data structures
//             - initializes BCRec boundary condition object
AmrCoreLBM::AmrCoreLBM(ProblemInit problem_init)
  : m_problem_init(problem_init) {
  AMREX_ALWAYS_ASSERT(m_problem_init != nullptr);

  ReadParameters();

#if (AMREX_SPACEDIM == 3)
  AMREX_ALWAYS_ASSERT_WITH_MESSAGE(
      max_level == 0, "LBM3D requires amr.max_level=0.");
  AMREX_ALWAYS_ASSERT_WITH_MESSAGE(ndir == 19,
                                   "LBM3D requires lbm3d.ndir=19 (D3Q19).");
#endif

  // Geometry on all levels has been defined already.

  // No valid BoxArray and DistributionMapping have been defined.
  // But the arrays for them have been resized.

  int nlevs_max = max_level + 1;

  istep.resize(nlevs_max, 0);
  nsubsteps.resize(nlevs_max, 1);

  for (int lev = 1; lev <= max_level; ++lev) {
    nsubsteps[lev] = MaxRefRatio(lev - 1);
  }

  t_new.resize(nlevs_max, 0.0);
  t_old.resize(nlevs_max, -1.e100);
  dt.resize(nlevs_max, 1.e100);

  xCellSize.resize(nlevs_max, 0.0);
  yCellSize.resize(nlevs_max, 0.0);
  zCellSize.resize(nlevs_max, 0.0);

  for (int lev = 0; lev <= max_level; ++lev) {
    xCellSize[lev] = geom[lev].CellSize(0);
    yCellSize[lev] = geom[lev].CellSize(1);
    zCellSize[lev] = geom[lev].CellSize(2);
  }
  // With c = dx/dt = 1 and cs^2 = 1/3, the physical viscosity is
  //   nu = cs^2 (tau - 1/2) dt = (tau - 1/2) dt / 3.
  // Since dt = dx in this code, keeping nu fixed requires
  //   tau - 1/2 = 3 nu / dx.
  tau_base = 3.0 * nu / xCellSize[0] + 0.5;

  tau.resize(nlevs_max, 0.0);
  dt[0] = xCellSize[0];
  tau[0] = tau_base;

  for (int lev = 1; lev <= max_level; ++lev) {
    dt[lev] = xCellSize[lev];
    // Keep the physical viscosity fixed across AMR levels.
    // With lattice scaling dt_lev ~ dx_lev, BGK requires
    //   nu = c_s^2 (tau_lev - 1/2) dt_lev
    // so tau_lev - 1/2 must scale like 1 / dt_lev ~ 1 / dx_lev.
    tau[lev] = 0.5 + 3.0 * nu / xCellSize[lev];
  }

  f_new.resize(nlevs_max);
  f_old.resize(nlevs_max);
  macro_new.resize(nlevs_max);
  macro_old.resize(nlevs_max);

  if (m_use_cylinder) {
    amrex::Print() << "Using IBM with method = " << m_ib_method << std::endl;
    // just one forcing
    forcing.resize(nlevs_max);
  }
  // set up boundary conditions

  using namespace BCVals;

  int bc_lo[AMREX_SPACEDIM];
  int bc_hi[AMREX_SPACEDIM];

  // 1) Define bc_lo/bc_hi and bcval for both periodic and non-periodic cases
  if (!(geom[0].isAllPeriodic())) {

    amrex::Vector<int> temp0, temp1;
    ParmParse pp("amrbc");

    pp.getarr("bc_lo", temp0);
    pp.getarr("bc_hi", temp1);

    for (int idim = 0; idim < AMREX_SPACEDIM; ++idim) {
      bc_lo[idim] = temp0[idim];
      bc_hi[idim] = temp1[idim];

      if (bc_lo[idim] == amrex::BCType::ext_dir ||
          bc_lo[idim] == amrex::BCType::user_1 ||
          bc_lo[idim] == amrex::BCType::user_2) {
        std::string dir = std::to_string(idim);
        pp.query(("bc_lo_" + dir + "_rho_val").c_str(),
                 BCVals::bc_lo_rho_val[idim]);
        pp.query(("bc_lo_" + dir + "_ux_val").c_str(),
                 BCVals::bc_lo_ux_val[idim]);
        pp.query(("bc_lo_" + dir + "_uy_val").c_str(),
                 BCVals::bc_lo_uy_val[idim]);
        pp.query(("bc_lo_" + dir + "_uz_val").c_str(),
                 BCVals::bc_lo_uz_val[idim]);
      }
      if (bc_hi[idim] == amrex::BCType::ext_dir ||
          bc_hi[idim] == amrex::BCType::user_1 ||
          bc_hi[idim] == amrex::BCType::user_2) {
        std::string dir = std::to_string(idim);
        pp.query(("bc_hi_" + dir + "_rho_val").c_str(),
                 BCVals::bc_hi_rho_val[idim]);
        pp.query(("bc_hi_" + dir + "_ux_val").c_str(),
                 BCVals::bc_hi_ux_val[idim]);
        pp.query(("bc_hi_" + dir + "_uy_val").c_str(),
                 BCVals::bc_hi_uy_val[idim]);
        pp.query(("bc_hi_" + dir + "_uz_val").c_str(),
                 BCVals::bc_hi_uz_val[idim]);
      }
    }

    for (int idim = 0; idim < AMREX_SPACEDIM; ++idim) {
      bcval.lo_rho[idim] = BCVals::bc_lo_rho_val[idim];
      bcval.lo_ux[idim] = BCVals::bc_lo_ux_val[idim];
      bcval.lo_uy[idim] = BCVals::bc_lo_uy_val[idim];
      bcval.lo_uz[idim] = BCVals::bc_lo_uz_val[idim];
      bcval.hi_rho[idim] = BCVals::bc_hi_rho_val[idim];
      bcval.hi_ux[idim] = BCVals::bc_hi_ux_val[idim];
      bcval.hi_uy[idim] = BCVals::bc_hi_uy_val[idim];
      bcval.hi_uz[idim] = BCVals::bc_hi_uz_val[idim];
    }

  } else {
    // Fully periodic: still must provide valid BCRec vectors for FillPatch.
    for (int idim = 0; idim < AMREX_SPACEDIM; ++idim) {
      bc_lo[idim] = amrex::BCType::int_dir;
      bc_hi[idim] = amrex::BCType::int_dir;

      // Not used for int_dir, but keep defined.
      bcval.lo_rho[idim] = amrex::Real(0.0);
      bcval.lo_ux[idim] = amrex::Real(0.0);
      bcval.lo_uy[idim] = amrex::Real(0.0);
      bcval.lo_uz[idim] = amrex::Real(0.0);
      bcval.hi_rho[idim] = amrex::Real(0.0);
      bcval.hi_ux[idim] = amrex::Real(0.0);
      bcval.hi_uy[idim] = amrex::Real(0.0);
      bcval.hi_uz[idim] = amrex::Real(0.0);
    }
  }

  if (ndir > BCBuf::MAX_NDIR) {
    amrex::Abort("LBM ndir exceeds BCBuf::MAX_NDIR (27).");
  }
  bcval.ndir = ndir;
  for (int q = 0; q < ndir; ++q) {
    bcval.dirx[q] = dirx[q];
    bcval.diry[q] = diry[q];
    bcval.dirz[q] = dirz[q];
    bcval.wi[q] = wi[q];
  }

  // 2) ALWAYS build BCRec vectors (required even if domain is periodic)
  bcsMesoscopic.resize(ndir);
  for (int c = 0; c < ndir; ++c) {
    for (int idim = 0; idim < AMREX_SPACEDIM; ++idim) {
      bcsMesoscopic[c].setLo(idim, bc_lo[idim]);
      bcsMesoscopic[c].setHi(idim, bc_hi[idim]);
    }
  }

  bcsMacro.resize(nmac);
  for (int c = 0; c < nmac; ++c) {
    for (int idim = 0; idim < AMREX_SPACEDIM; ++idim) {
      bcsMacro[c].setLo(idim, bc_lo[idim]);
      bcsMacro[c].setHi(idim, bc_hi[idim]);
    }
  }

  amrex::Print() << "AmrCoreLBM::AmrCoreLBM() finished." << std::endl;
}

AmrCoreLBM::~AmrCoreLBM() {}

// advance solution to final time
void AmrCoreLBM::Evolve() {

  Real cur_time = t_new[0];
  int last_plot_file_step = 0;
  Real wall_time_limit_s = 0.0;
  ParmParse("lbm3d").query("wall_time_limit_s", wall_time_limit_s);
  int mass_check_interval = 100;
  ParmParse("lbm3d").query("mass_check_interval", mass_check_interval);
  AMREX_ALWAYS_ASSERT_WITH_MESSAGE(mass_check_interval > 0,
                                   "lbm3d.mass_check_interval must be positive");
  const Real wall_start = amrex::second();
  const int first_step = istep[0];

  for (int step = istep[0]; step < max_step && cur_time < stop_time; ++step) {
    amrex::Print() << "\nCoarse STEP " << step + 1 << " starts ..."
                   << std::endl;

    int lev = 0;
    int iteration = 1;

    timeStepWithSubcycling(lev, cur_time, iteration);

    cur_time += dt[0];

    // The global mass reduction synchronizes all GPUs. Sample it at a
    // configurable interval while retaining the first and final checks.
    const bool check_mass =
        (step == first_step) || ((step + 1) % mass_check_interval == 0) ||
        (step + 1 == max_step) ||
        (cur_time >= stop_time - 1.e-6 * dt[0]) ||
        (m_force_validation && m_use_prescribed_force);
    Real sum_rho = 0.0;
    if (check_mass) {
      sum_rho = macro_new[0].sum(0);
    }

    // Simple forcing validation: for a fully periodic box with spatially
    // uniform forcing and initially uniform fields, the domain-averaged
    // velocity should follow u(t) ~ (t/dt - 0.5) * Fx / rho (with Fx the
    // LBM forcing term dt*force_density). This is a strong sanity check that
    // your Guo forcing path + macro update are wired correctly.
    if (m_force_validation && m_use_prescribed_force) {
      const auto& dom = geom[0].Domain();
      const long ncell = static_cast<long>(dom.numPts());
      Real mean_u = macro_new[0].sum(1) / static_cast<Real>(ncell);
      Real mean_v = macro_new[0].sum(2) / static_cast<Real>(ncell);
      Real mean_rho = sum_rho / static_cast<Real>(ncell);
      const Real dt0 = dt[0];
      const Real Fx = m_prescribed_force[0];
      const Real Fy = m_prescribed_force[1];
      // predicted mean velocity using the standard half-step velocity definition
      Real u_pred = (cur_time / dt0 - amrex::Real(0.5)) * Fx / mean_rho;
      Real v_pred = (cur_time / dt0 - amrex::Real(0.5)) * Fy / mean_rho;
      // Also report mean raw momentum m = sum_q f*c (i.e. without the +0.5F shift)
const Real mean_momx = mean_rho * mean_u - amrex::Real(0.5) * Fx;
const Real mean_momy = mean_rho * mean_v - amrex::Real(0.5) * Fy;
amrex::Print() << std::setprecision(12)
                     << "  [force_validation] <rho>=" << mean_rho
                     << " <u>=" << mean_u << " pred=" << u_pred << " <momx>=" << mean_momx
                     << " <v>=" << mean_v << " pred=" << v_pred << " <momy>=" << mean_momy
                     << " (t=" << cur_time << ")\n";
    }

    if (m_use_cylinder && m_force_interval > 0 &&
        ((step + 1) % m_force_interval == 0)) {
      ComputeIBForce(cur_time, step + 1);
    }

    amrex::Print() << "Coarse STEP " << step + 1 << " ends."
                   << " TIME = " << cur_time << " DT = " << dt[0];
    if (check_mass) {
      amrex::Print() << " Sum(Rho) = " << sum_rho;
    }
    amrex::Print() << std::endl;

    // sync up time
    for (lev = 0; lev <= finest_level; ++lev) {
      t_new[lev] = cur_time;
    }

    if (plot_int > 0 && (step + 1) % plot_int == 0) {
      last_plot_file_step = step + 1;
      // Keep derived diagnostics (e.g. vorticity/pressure) synchronized with
      // the just-advanced velocity field on every level at plot output times.
      for (int lev_plot = 0; lev_plot <= finest_level; ++lev_plot) {
        UpdateDerivedMacroFields(lev_plot, t_new[lev_plot]);
      }
      WritePlotFile();
    }

    if (chk_int > 0 && (step + 1) % chk_int == 0) {
      WriteCheckpointFile();
    }

#ifdef AMREX_MEM_PROFILING
    {
      std::ostringstream ss;
      ss << "[STEP " << step + 1 << "]";
      MemProfiler::report(ss.str());
    }
#endif

    if (cur_time >= stop_time - 1.e-6 * dt[0])
      break;

    if (wall_time_limit_s > 0.0) {
      Real elapsed = amrex::second() - wall_start;
      amrex::ParallelDescriptor::ReduceRealMax(elapsed);
      if (elapsed >= wall_time_limit_s) {
        amrex::Print() << "LBM wall time limit reached after " << elapsed
                       << " s at step " << step + 1 << '\n';
        break;
      }
    }

  }

  if (plot_int > 0 && istep[0] > last_plot_file_step) {
    for (int lev_plot = 0; lev_plot <= finest_level; ++lev_plot) {
      UpdateDerivedMacroFields(lev_plot, t_new[lev_plot]);
    }
    WritePlotFile();
  }
}

// initializes multilevel data
void AmrCoreLBM::InitData() {
  ResetForceHistory();

  if (restart_chkfile == "") {
    // start simulation from the beginning
    const Real time = 0.0;
    InitFromScratch(time);

    AverageDown();
    // Derived fields such as vorticity/pressure must be refreshed after
    // initialization-level averaging so the t=0 plotfile reflects the
    // initialized velocity field instead of whatever placeholder values
    // were written by the problem setup.
    for (int lev = 0; lev <= finest_level; ++lev) {
      UpdateDerivedMacroFields(lev, time);
      MultiFab::Copy(macro_old[lev], macro_new[lev], 0, 0, nmac, nghost);
    }
    if (m_use_cylinder && m_ls) {
      for (int lev = 0; lev <= finest_level; ++lev) {
        BuildLevelSetOnLevel(lev);
      }
    }

    /*
if (chk_int > 0) {
WriteCheckpointFile();
}
    */
  } else {
    // restart from a checkpoint
    // ReadCheckpointFile();
    for (int lev = 0; lev <= finest_level; ++lev) {
      if (macro_new[lev].ok()) {
        UpdateDerivedMacroFields(lev, t_new[lev]);
      }
    }
  }

  if (plot_int > 0) {

    WritePlotFile();
  }
}

// Make a new level using provided BoxArray and DistributionMapping and
// fill with interpolated coarse level data.
// overrides the pure virtual function in AmrCore
void AmrCoreLBM::MakeNewLevelFromCoarse(int lev, Real time, const BoxArray &ba,
                                        const DistributionMapping &dm) {

  const int f_ncomp = f_new[lev - 1].nComp();
  const int f_nghost = f_new[lev - 1].nGrow();
  const int m_ncomp = macro_new[lev - 1].nComp();
  const int m_nghost = macro_new[lev - 1].nGrow();

  f_new[lev].define(ba, dm, f_ncomp, f_nghost);
  f_old[lev].define(ba, dm, f_ncomp, f_nghost);
  macro_new[lev].define(ba, dm, m_ncomp, m_nghost);
  macro_old[lev].define(ba, dm, m_ncomp, m_nghost);

  t_new[lev] = time;
  t_old[lev] = time - 1.e200;

  // This part requires special attention. For AMR stability, do not
  // interpolate the mesoscopic populations f_i from coarse to fine. Instead,
  // initialize macros first and reconstruct f_i from equilibrium.
  FillCoarsePatchMacro(lev, time, macro_new[lev], 0, m_ncomp);
  MultiFab::Copy(macro_old[lev], macro_new[lev], 0, 0, m_ncomp, m_nghost);

  {
    auto const *wi_d = wi_dev.data();
    auto const *cx_d = dirx_dev.data();
    auto const *cy_d = diry_dev.data();
    auto const *cz_d = dirz_dev.data();
    const int ndir_l = ndir;

#ifdef AMREX_USE_OMP
#pragma omp parallel if (Gpu::notInLaunchRegion())
#endif
    for (MFIter mfi(f_new[lev], TilingIfNotGPU()); mfi.isValid(); ++mfi) {

      const Box &bx = mfi.fabbox();

      auto const rho = macro_new[lev][mfi].const_array(0);
      auto const ux = macro_new[lev][mfi].const_array(1);
      auto const uy = macro_new[lev][mfi].const_array(2);
      auto const uz = macro_new[lev][mfi].const_array(3);

      auto const f = f_new[lev][mfi].array();
      auto const fo = f_old[lev][mfi].array();

      amrex::ParallelFor(bx, [=] AMREX_GPU_DEVICE(int i, int j,
                                                  int k) noexcept {
        Real r = amrex::max(rho(i, j, k), amrex::Real(1.e-12));
        Real u0 = ux(i, j, k);
        Real v0 = uy(i, j, k);
        Real w0 = uz(i, j, k);
        Real u2 = u0 * u0 + v0 * v0 + w0 * w0;

        for (int q = 0; q < ndir_l; ++q) {
          Real cu = cx_d[q] * u0 + cy_d[q] * v0 + cz_d[q] * w0;
          Real feq = wi_d[q] * r *
                     (amrex::Real(1.0) + amrex::Real(3.0) * cu + amrex::Real(4.5) * cu * cu - amrex::Real(1.5) * u2);
          f(i, j, k, q) = feq;
          fo(i, j, k, q) = feq;
        }
      });
    }
  }

  // --- Level-set φ on this level ---
  if (m_use_cylinder) {
    // --- Level-set φ on this level ---
    BuildLevelSetOnLevel(lev);
    const int nforce = 3;
    forcing[lev].define(ba, dm, nforce, m_nghost);
    forcing[lev].setVal(0.0);
  }

  // --- IBM object only for current finest (optional) ---
  if (lev == finestLevel()) {
    ResetIBMBackend();
    EnsureIBMBackend(lev, dm, ba);
  }

  UpdateDerivedMacroFields(lev, time);
}

// Remake an existing level using provided BoxArray and DistributionMapping and
// fill with existing fine and coarse data.
// overrides the pure virtual function in AmrCore
void AmrCoreLBM::RemakeLevel(int lev, Real time, const BoxArray &ba,
                             const DistributionMapping &dm) {

  const int f_ncomp = f_new[lev].nComp();
  const int f_nghost = f_new[lev].nGrow();
  const int m_ncomp = macro_new[lev].nComp();
  const int m_nghost = macro_new[lev].nGrow();

  MultiFab newF_state(ba, dm, f_ncomp, f_nghost);
  MultiFab oldF_state(ba, dm, f_ncomp, f_nghost);
  MultiFab newM_state(ba, dm, m_ncomp, m_nghost);
  MultiFab oldM_state(ba, dm, m_ncomp, m_nghost);
  // Fill macroscopic state first (time-consistent), then reconstruct mesoscopic
  // populations from equilibrium. This is significantly more robust across AMR
  // regrids/remaps than interpolating f_i directly.
  FillPatchMacro(lev, time, newM_state, 0, m_ncomp);
  MultiFab::Copy(oldM_state, newM_state, 0, 0, m_ncomp, m_nghost);

  {
    auto const *wi_d = wi_dev.data();
    auto const *cx_d = dirx_dev.data();
    auto const *cy_d = diry_dev.data();
    auto const *cz_d = dirz_dev.data();
    const int ndir_l = ndir;

#ifdef AMREX_USE_OMP
#pragma omp parallel if (Gpu::notInLaunchRegion())
#endif
    for (MFIter mfi(newF_state, TilingIfNotGPU()); mfi.isValid(); ++mfi) {

      const Box &bx = mfi.fabbox();

      auto const rho = newM_state[mfi].const_array(0);
      auto const ux = newM_state[mfi].const_array(1);
      auto const uy = newM_state[mfi].const_array(2);
      auto const uz = newM_state[mfi].const_array(3);

      auto const f = newF_state[mfi].array();
      auto const fo = oldF_state[mfi].array();

      amrex::ParallelFor(bx, [=] AMREX_GPU_DEVICE(int i, int j,
                                                  int k) noexcept {
        Real r = amrex::max(rho(i, j, k), amrex::Real(1.e-12));
        Real u0 = ux(i, j, k);
        Real v0 = uy(i, j, k);
        Real w0 = uz(i, j, k);
        Real u2 = u0 * u0 + v0 * v0 + w0 * w0;

        for (int q = 0; q < ndir_l; ++q) {
          Real cu = cx_d[q] * u0 + cy_d[q] * v0 + cz_d[q] * w0;
          Real feq = wi_d[q] * r *
                     (amrex::Real(1.0) + amrex::Real(3.0) * cu + amrex::Real(4.5) * cu * cu - amrex::Real(1.5) * u2);
          f(i, j, k, q) = feq;
          fo(i, j, k, q) = feq;
        }
      });
    }
  }

  std::swap(newF_state, f_new[lev]);
  std::swap(oldF_state, f_old[lev]);
  std::swap(newM_state, macro_new[lev]);
  std::swap(oldM_state, macro_old[lev]);
  // --- Level-set φ on this level ---
  if (m_use_cylinder) {
    // --- Level-set φ on this level ---
    BuildLevelSetOnLevel(lev);
    const int nforce = 3;
    forcing[lev].define(ba, dm, nforce, m_nghost);
    forcing[lev].setVal(0.0);
  }

  // --- IBM object only for current finest (optional) ---
  if (lev == finestLevel()) {
    ResetIBMBackend();
    EnsureIBMBackend(lev, dm, ba);
  }

  UpdateDerivedMacroFields(lev, time);
}

// Delete level data
// overrides the pure virtual function in AmrCore
void AmrCoreLBM::ClearLevel(int lev) {
  f_new[lev].clear();
  f_old[lev].clear();
  macro_new[lev].clear();
  macro_old[lev].clear();
  if (m_use_cylinder && lev < static_cast<int>(forcing.size())) {
    forcing[lev].clear();
  }
}

// Make a new level from scratch using provided BoxArray and
// DistributionMapping. Only used during initialization. overrides the pure
// virtual function in AmrCore
void AmrCoreLBM::MakeNewLevelFromScratch(int lev, Real time, const BoxArray &ba,
                                         const DistributionMapping &dm) {

  amrex::Print() << "Making new level " << lev << std::endl;

  f_new[lev].define(ba, dm, ndir, nghost);
  f_old[lev].define(ba, dm, ndir, nghost);
  macro_new[lev].define(ba, dm, nmac, nghost);
  macro_old[lev].define(ba, dm, nmac, nghost);

  if (m_use_cylinder) {
    // --- Level-set φ on this level ---
    BuildLevelSetOnLevel(lev);
    const int nforce = 3;
    forcing[lev].define(ba, dm, nforce, nghost);
    forcing[lev].setVal(0.0);
  }

  // --- IBM object only for current finest (optional) ---
  if (lev == finestLevel()) {
    ResetIBMBackend();
    EnsureIBMBackend(lev, dm, ba);
  }

  MultiFab &cur = macro_new[lev];

  m_problem_init(cur, Geom(lev), nu);

  UpdateDerivedMacroFields(lev, time);

  MultiFab::Copy(macro_old[lev], macro_new[lev], 0, 0, nmac, nghost);

  InitEquilibrium();
}

// tag all cells for refinement
// overrides the pure virtual function in AmrCore
void AmrCoreLBM::ErrorEst(int lev, TagBoxArray &tags, Real time,
                          int /*ngrow*/) {

  static bool first = true;
  static Vector<Real> thresholdRatio;
  static Real no_refine_xlo = amrex::Real(0.0);
  static Real no_refine_xhi = amrex::Real(0.0);

  // only do this during the first call to ErrorEst
  if (first) {
    first = false;
    // read in an array of "phierr", which is the tagging threshold
    // in this example, we tag values of "phi" which are greater than phierr
    // for that particular level
    // in subroutine state_error, you could use more elaborate tagging, such
    // as more advanced logical expressions, or gradients, etc.
    ParmParse pp("amrvorth");
    int n = pp.countval("thresholdRatio");
    if (n > 0) {
      pp.getarr("thresholdRatio", thresholdRatio, 0, n);
    }
    pp.query("no_refine_xlo", no_refine_xlo);
    pp.query("no_refine_xhi", no_refine_xhi);

    // Ensure thresholdRatio is defined for all levels [0..max_level]
    if (thresholdRatio.empty()) {
      thresholdRatio.resize(max_level + 1, amrex::Real(1.0));
    } else if (static_cast<int>(thresholdRatio.size()) < max_level + 1) {
      thresholdRatio.resize(max_level + 1, thresholdRatio.back());
    }
  }

  MultiFab macro_tag(grids[lev], dmap[lev], 4, 1);
  FillPatchMacro(lev, time, macro_tag, 0, 4);
  MultiFab vort_for_tag(grids[lev], dmap[lev], 1, 0);

  const auto dx_arr = geom[lev].CellSizeArray();
  const Real dx_tag = dx_arr[0];
  const Real dy_tag = dx_arr[1];
#if (AMREX_SPACEDIM == 3)
  const Real dz_tag = dx_arr[2];
#else
  const Real dz_tag = Real(0.0);
#endif

#ifdef AMREX_USE_OMP
#pragma omp parallel if (Gpu::notInLaunchRegion())
#endif
  for (MFIter mfi(vort_for_tag, TilingIfNotGPU()); mfi.isValid(); ++mfi) {
    const Box &bx = mfi.validbox();
    const int K = mfi.index();
    auto const u = macro_tag[K].array(1);
    auto const v = macro_tag[K].array(2);
    auto const w = macro_tag[K].array(3);
    auto const vort = vort_for_tag[K].array(0);
    amrex::ParallelFor(bx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
      vort(i, j, k) = vorticityDiagnostic(i, j, k, u, v, w, dx_tag, dy_tag,
                                          dz_tag);
    });
  }

  // Max vorticity used for tagging on this level, computed from a
  // coarse/fine-consistent ghost-filled macro patch.
  amrex::Real vortMax = vort_for_tag.max(0);
  const amrex::Real dx_min = xCellSize[lev];
  const auto dx = geom[lev].CellSizeArray();
  const auto problo = geom[lev].ProbLoArray();
  const auto probhi = geom[lev].ProbHiArray();
  const Real no_refine_xlo_local = no_refine_xlo;
  const Real no_refine_xhi_local = no_refine_xhi;
  Real refine_xlo = amrex::Real(0.0);
  Real refine_xhi = amrex::Real(0.0);
  Real refine_ylo = amrex::Real(0.0);
  Real refine_yhi = amrex::Real(0.0);
  Real refine_zlo = amrex::Real(0.0);
  Real refine_zhi = amrex::Real(0.0);
  const bool have_body_refine_region =
      m_use_cylinder &&
      immersed_boundary_refinement_region(
          m_ls_par.x0, m_ls_par.y0, m_ls_par.z0, m_ls_par.R, m_marker_par,
          dx_min, refine_xlo, refine_xhi, refine_ylo, refine_yhi, refine_zlo,
          refine_zhi);
  const bool marker_levelset_ibm =
      (m_ib_method != IBMMethodMarker ||
       m_marker_par.geometry_type == MarkerIBParams::GeometryCylinder);
  if (m_use_cylinder && marker_levelset_ibm && m_ls && m_ls->has_level(lev)) {
    // Level set φ for this level
    MultiFab &phi_mf = m_ls->phi_at(lev);

    const int clearval = TagBox::CLEAR;
    const int tagval = TagBox::SET;

#ifdef AMREX_USE_OMP
#pragma omp parallel if (Gpu::notInLaunchRegion())
#endif
    {

      for (MFIter mfi(vort_for_tag, TilingIfNotGPU()); mfi.isValid(); ++mfi) {
        const Box &bx = mfi.validbox();
        const int K = mfi.index();

        auto const &vort = vort_for_tag[K].const_array(0);
        // level set φ: component 0 of m_ls->phi_at(lev)

        auto const &phi_arr = phi_mf[K].const_array(0);

        auto const &tagfab = tags[K].array();

        Real threshold = thresholdRatio[lev] * vortMax;
        constexpr int n_cells_band = 5;

        amrex::ParallelFor(
            bx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
              const Real x = problo[0] + (Real(i) + Real(0.5)) * dx[0];
              const Real xlo_block = problo[0] + no_refine_xlo_local;
              const Real xhi_block = probhi[0] - no_refine_xhi_local;
              if (no_refine_xlo_local > Real(0.0) || no_refine_xhi_local > Real(0.0)) {
                if (x <= xlo_block || x >= xhi_block) {
                  tagfab(i, j, k) = clearval;
                  return;
                }
              }
              // Tag by vorticity
              vorticity_tagging(i, j, k, tagfab, vort, threshold, tagval);

              // Tag by level-set band around structure
              levelset_tagging(i, j, k, tagfab, phi_arr, dx_min, n_cells_band,
                               tagval);

              if (have_body_refine_region) {
                const Real x = problo[0] + (Real(i) + Real(0.5)) * dx[0];
                const Real y = problo[1] + (Real(j) + Real(0.5)) * dx[1];
#if (AMREX_SPACEDIM == 3)
                const Real z = problo[2] + (Real(k) + Real(0.5)) * dx[2];
#else
                const Real z = amrex::Real(0.0);
#endif
                if (x >= refine_xlo && x <= refine_xhi && y >= refine_ylo &&
                    y <= refine_yhi && z >= refine_zlo && z <= refine_zhi) {
                  tagfab(i, j, k) = tagval;
                }
              }
            });
      }
    }

  } else {
    const int clearval = TagBox::CLEAR;
    const int tagval = TagBox::SET;

#ifdef AMREX_USE_OMP
#pragma omp parallel if (Gpu::notInLaunchRegion())
#endif
    {

      for (MFIter mfi(vort_for_tag, TilingIfNotGPU()); mfi.isValid(); ++mfi) {
        const Box &bx = mfi.validbox();
        const int K = mfi.index();

        auto const &vort = vort_for_tag[K].const_array(0);
        // level set φ: component 0 of m_ls->phi_at(lev)

        auto const &tagfab = tags[K].array();

        Real threshold = thresholdRatio[lev] * vortMax;

        amrex::ParallelFor(
            bx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
              const Real x = problo[0] + (Real(i) + Real(0.5)) * dx[0];
              const Real xlo_block = problo[0] + no_refine_xlo_local;
              const Real xhi_block = probhi[0] - no_refine_xhi_local;
              if (no_refine_xlo_local > Real(0.0) || no_refine_xhi_local > Real(0.0)) {
                if (x <= xlo_block || x >= xhi_block) {
                  tagfab(i, j, k) = clearval;
                  return;
                }
              }
              // Tag by vorticity
              vorticity_tagging(i, j, k, tagfab, vort, threshold, tagval);

              if (have_body_refine_region) {
                const Real x = problo[0] + (Real(i) + Real(0.5)) * dx[0];
                const Real y = problo[1] + (Real(j) + Real(0.5)) * dx[1];
#if (AMREX_SPACEDIM == 3)
                const Real z = problo[2] + (Real(k) + Real(0.5)) * dx[2];
#else
                const Real z = amrex::Real(0.0);
#endif
                if (x >= refine_xlo && x <= refine_xhi && y >= refine_ylo &&
                    y <= refine_yhi && z >= refine_zlo && z <= refine_zhi) {
                  tagfab(i, j, k) = tagval;
                }
              }
            });
      }
    }
  }
}

// read in some parameters from inputs file
void AmrCoreLBM::ReadParameters() {
  {
    ParmParse pp; // Traditionally, max_step and stop_time do not have prefix.
    pp.query("max_step", max_step);
    pp.query("stop_time", stop_time);
  }
  amrex::Print() << " max_step = " << max_step << std::endl;
  amrex::Print() << " stop_time = " << stop_time << std::endl;
  {
    ParmParse pp("amr"); // Traditionally, these have prefix, amr.

    pp.query("regrid_int", regrid_int);
    pp.query("plot_file", plot_file);
    pp.query("plot_int", plot_int);
    pp.query("chk_file", chk_file);
    pp.query("chk_int", chk_int);
    pp.query("restart", restart_chkfile);
  }

  {
    if (AMREX_SPACEDIM == 2) {
      ParmParse pp("lbm2d");

      pp.query("ndir", ndir);
      pp.queryarr("wis", wis);
      pp.queryarr("wim", wim);
      pp.queryarr("dirx", dirx);
      pp.queryarr("diry", diry);
      pp.queryarr("dirz", dirz);

      wi.resize(wis.size());
      for (size_t idvs = 0; idvs < wis.size(); idvs++) {
        wi[idvs] = wis[idvs] / wim[idvs];
      }
    }

    if (AMREX_SPACEDIM == 3) {
      ParmParse pp("lbm3d");

      pp.query("ndir", ndir);
      pp.queryarr("wis", wis);
      pp.queryarr("wim", wim);
      pp.queryarr("dirx", dirx);
      pp.queryarr("diry", diry);
      pp.queryarr("dirz", dirz);
      wi.resize(wis.size());
      for (size_t idvs = 0; idvs < wis.size(); idvs++) {
        wi[idvs] = wis[idvs] / wim[idvs];
      }
    }

    {
      ParmParse pp("lbmPhysicalParameters");
      pp.query("nu", nu);
      pp.query("nmac", nmac);
      U0 = amrex::Real(0.1);
      pp.query("U0", U0);
    }

    // ------------------------------------------------------------
    // Optional: prescribed forcing for validation / simple forcing tests
    // Convention: values are the LBM forcing terms passed to Guo forcing,
    // i.e. (dt * force_density) in lattice units.
    // Example: lbm.prescribed_force = 1e-6 0 0
    //          lbm.force_validation = 1
    {
      ParmParse pp_lbm("lbm");
      amrex::Vector<amrex::Real> Ftmp;
      if (pp_lbm.queryarr("prescribed_force", Ftmp) && Ftmp.size() >= 2) {
        m_use_prescribed_force = true;
        m_prescribed_force[0] = Ftmp[0];
        m_prescribed_force[1] = Ftmp[1];
        m_prescribed_force[2] = (Ftmp.size() > 2) ? Ftmp[2] : amrex::Real(0.0);
      }
      pp_lbm.query("force_validation", m_force_validation);
      if (m_use_prescribed_force) {
        amrex::Print() << "LBM prescribed_force = (" << m_prescribed_force[0]
                       << ", " << m_prescribed_force[1] << ", "
                       << m_prescribed_force[2] << ")" << std::endl;
      }
    }

    {
      amrex::ParmParse pp_ibm("ibm");

      // optional toggle (defaults are OK if missing)
      pp_ibm.query("use_cylinder", m_use_cylinder);

      std::string method = "none";
      pp_ibm.query("method", method);
      if (method == "0" || method == "none" || method.empty()) {
        m_ib_method = IBMMethodNone;
      } else if (method == "1" || method == "marker" || method == "iamr_marker") {
        m_ib_method = IBMMethodMarker;
      } else if (method == "diffuse" || method == "sharp") {
        amrex::Abort("ibm.method = " + method +
                     " is not enabled in the current code base. "
                     "Only the validated marker backend "
                     "(`ibm.method = 1`) is supported.");
      } else {
        amrex::Abort("Unknown ibm.method = " + method +
                     ". Supported values are: 0, 1, none, marker, iamr_marker.");
      }

      // Geometry shared by the validated marker backend.
      pp_ibm.query("x0", m_ls_par.x0);
      pp_ibm.query("y0", m_ls_par.y0);
      pp_ibm.query("z0", m_ls_par.z0);
      pp_ibm.query("R", m_ls_par.R);

      // IAMReX-style marker DF parameters
      pp_ibm.query("delta_type", m_marker_par.delta_type); // 0:4pt, 1:3pt
      pp_ibm.query("loop_ns", m_marker_par.loop_ns);
      pp_ibm.query("mdf_relax", m_marker_par.mdf_relax);
      pp_ibm.query("n_marker", m_marker_par.n_marker);
      pp_ibm.query("refine_upstream", m_marker_par.refine_upstream);
      pp_ibm.query("refine_downstream", m_marker_par.refine_downstream);
      pp_ibm.query("refine_cross", m_marker_par.refine_cross);
      pp_ibm.query("rd", m_marker_par.rd);
      std::string marker_geometry = "cylinder";
      pp_ibm.query("marker_geometry", marker_geometry);
      if (marker_geometry == "box" || marker_geometry == "cavity_box") {
        m_marker_par.geometry_type = MarkerIBParams::GeometryBox;
      } else if (marker_geometry == "pitching_airfoil" ||
                 marker_geometry == "user_defined" ||
                 marker_geometry == "custom") {
        m_marker_par.geometry_type = MarkerIBParams::GeometryUserDefined;
      } else {
        m_marker_par.geometry_type = MarkerIBParams::GeometryCylinder;
      }
      pp_ibm.query("box_xlo", m_marker_par.box_xlo);
      pp_ibm.query("box_xhi", m_marker_par.box_xhi);
      pp_ibm.query("box_ylo", m_marker_par.box_ylo);
      pp_ibm.query("box_yhi", m_marker_par.box_yhi);
      pp_ibm.query("box_zlo", m_marker_par.box_zlo);
      pp_ibm.query("box_zhi", m_marker_par.box_zhi);
      pp_ibm.query("box_ds", m_marker_par.box_ds);
      pp_ibm.query("box_lid_only", m_marker_par.box_lid_only);
      pp_ibm.query("box_lid_ux", m_marker_par.box_lid_ux);
      pp_ibm.query("box_lid_uy", m_marker_par.box_lid_uy);
      pp_ibm.query("box_lid_uz", m_marker_par.box_lid_uz);
      pp_ibm.query("box_wall_tol", m_marker_par.box_wall_tol);
      pp_ibm.query("ubx", m_marker_par.ubx);
      pp_ibm.query("uby", m_marker_par.uby);
      pp_ibm.query("ubz", m_marker_par.ubz);
      pp_ibm.query("omx", m_marker_par.omx);
      pp_ibm.query("omy", m_marker_par.omy);
      pp_ibm.query("omz", m_marker_par.omz);
      pp_ibm.query("verbose", m_marker_par.verbose);
      std::string coupling_method = "ivc";
      pp_ibm.query("coupling_method", coupling_method);
      if (coupling_method == "ivc" || coupling_method == "wu_shu") {
        m_marker_par.coupling_method = MarkerIBParams::CouplingIVC;
      } else if (coupling_method == "explicit_diag" ||
                 coupling_method == "diag_ivc") {
        m_marker_par.coupling_method = MarkerIBParams::CouplingExplicitDiag;
      } else {
        m_marker_par.coupling_method = MarkerIBParams::CouplingExplicit;
      }
      pp_ibm.query("explicit_diag_eps", m_marker_par.explicit_diag_eps);
      pp_ibm.query("ivc_diag_reg", m_marker_par.ivc_diag_reg);
      pp_ibm.query("ivc_rebuild_matrix", m_marker_par.ivc_rebuild_matrix);
      pp_ibm.query("ivc_verbose", m_marker_par.ivc_verbose);
      pp_ibm.query("force_interval", m_force_interval);
      pp_ibm.query("force_file", m_force_file);
      std::string force_eval_method = "momentum_exchange";
      pp_ibm.query("force_eval_method", force_eval_method);
      if (force_eval_method == "eulerian") {
        m_force_eval_method = ForceEvalEulerian;
      } else if (force_eval_method == "marker") {
        m_force_eval_method = ForceEvalMarker;
      } else {
        m_force_eval_method = ForceEvalMomentumExchange;
      }
      pp_ibm.query("force_eval_debug", m_force_eval_debug);
      // IAMReX-compatible aliases in the ibm.* namespace.
      pp_ibm.query("renormalize_delta", m_marker_par.renormalize_delta);
      pp_ibm.query("delta_renorm", m_marker_par.renormalize_delta);
      pp_ibm.query("debug_force_balance", m_marker_par.debug_force_balance);
      pp_ibm.query("print_force_balance", m_marker_par.debug_force_balance);
      pp_ibm.query("debug_kernel_partition", m_marker_par.debug_kernel_partition);
      pp_ibm.query("print_delta_partition", m_marker_par.debug_kernel_partition);

      // Additional IAMReX-compatible marker DF knobs (nested namespace).
      // These commonly appear in inputs as ibm.marker_df.*
      {
        amrex::ParmParse pp_mdf("ibm.marker_df");
        pp_mdf.query("debug_force_balance", m_marker_par.debug_force_balance);
        pp_mdf.query("debug_kernel_partition", m_marker_par.debug_kernel_partition);
        pp_mdf.query("renormalize_delta", m_marker_par.renormalize_delta);
        pp_mdf.query("mdf_relax", m_marker_par.mdf_relax);
        pp_mdf.query("explicit_diag_eps", m_marker_par.explicit_diag_eps);
        pp_mdf.query("refine_upstream", m_marker_par.refine_upstream);
        pp_mdf.query("refine_downstream", m_marker_par.refine_downstream);
        pp_mdf.query("refine_cross", m_marker_par.refine_cross);
        std::string marker_geometry_mdf;
        if (pp_mdf.query("geometry", marker_geometry_mdf)) {
          if (marker_geometry_mdf == "box" || marker_geometry_mdf == "cavity_box") {
            m_marker_par.geometry_type = MarkerIBParams::GeometryBox;
          } else if (marker_geometry_mdf == "pitching_airfoil" ||
                     marker_geometry_mdf == "user_defined" ||
                     marker_geometry_mdf == "custom") {
            m_marker_par.geometry_type = MarkerIBParams::GeometryUserDefined;
          } else {
            m_marker_par.geometry_type = MarkerIBParams::GeometryCylinder;
          }
        }
        pp_mdf.query("box_xlo", m_marker_par.box_xlo);
        pp_mdf.query("box_xhi", m_marker_par.box_xhi);
        pp_mdf.query("box_ylo", m_marker_par.box_ylo);
        pp_mdf.query("box_yhi", m_marker_par.box_yhi);
        pp_mdf.query("box_zlo", m_marker_par.box_zlo);
        pp_mdf.query("box_zhi", m_marker_par.box_zhi);
        pp_mdf.query("box_ds", m_marker_par.box_ds);
        pp_mdf.query("box_lid_only", m_marker_par.box_lid_only);
        pp_mdf.query("box_lid_ux", m_marker_par.box_lid_ux);
        pp_mdf.query("box_lid_uy", m_marker_par.box_lid_uy);
        pp_mdf.query("box_lid_uz", m_marker_par.box_lid_uz);
        pp_mdf.query("box_wall_tol", m_marker_par.box_wall_tol);
        std::string coupling_method_mdf;
        if (pp_mdf.query("coupling_method", coupling_method_mdf)) {
          if (coupling_method_mdf == "ivc" || coupling_method_mdf == "wu_shu") {
            m_marker_par.coupling_method = MarkerIBParams::CouplingIVC;
          } else if (coupling_method_mdf == "explicit_diag" ||
                     coupling_method_mdf == "diag_ivc") {
            m_marker_par.coupling_method = MarkerIBParams::CouplingExplicitDiag;
          } else {
            m_marker_par.coupling_method = MarkerIBParams::CouplingExplicit;
          }
        }
        pp_mdf.query("ivc_diag_reg", m_marker_par.ivc_diag_reg);
        pp_mdf.query("ivc_rebuild_matrix", m_marker_par.ivc_rebuild_matrix);
        pp_mdf.query("ivc_verbose", m_marker_par.ivc_verbose);
      }

      amrex::Print() << "IBM parameters: use_cylinder = " << m_use_cylinder
                     << ", method = " << method << std::endl;
      amrex::Print() << "               x0 = " << m_ls_par.x0
                     << ", y0 = " << m_ls_par.y0 << ", z0 = " << m_ls_par.z0
                     << ", R = " << m_ls_par.R << std::endl;
      amrex::Print() << "               marker_geometry = "
                     << ((m_marker_par.geometry_type ==
                          MarkerIBParams::GeometryBox)
                             ? "box"
                             : ((m_marker_par.geometry_type ==
                                 MarkerIBParams::GeometryUserDefined)
                                    ? "pitching_airfoil"
                                    : "cylinder"))
                     << " (refine_upstream=" << m_marker_par.refine_upstream
                     << ", refine_downstream=" << m_marker_par.refine_downstream
                     << ", refine_cross=" << m_marker_par.refine_cross << ")\n";
      amrex::Print() << "               force_eval_method = " << force_eval_method
                     << " (" << m_force_eval_method << ")"
                     << ", force_file = " << m_force_file << "\n";
      amrex::Print() << "               marker_coupling = "
                     << ((m_marker_par.coupling_method ==
                          MarkerIBParams::CouplingIVC)
                             ? "ivc"
                             : ((m_marker_par.coupling_method ==
                                 MarkerIBParams::CouplingExplicitDiag)
                                    ? "explicit_diag"
                                    : "explicit"))
                     << " (loop_ns=" << m_marker_par.loop_ns
                     << ", mdf_relax=" << m_marker_par.mdf_relax << ")"
                     << " (explicit_diag_eps="
                     << m_marker_par.explicit_diag_eps << ")"
                     << " (ivc_diag_reg=" << m_marker_par.ivc_diag_reg
                     << ", ivc_rebuild_matrix="
                     << m_marker_par.ivc_rebuild_matrix << ")\n";

      // create managers
      m_ls = std::make_unique<LevelSetManager>();
      ResetIBMBackend();
    }

    int n_phi = (m_use_cylinder &&
                 m_marker_par.geometry_type == MarkerIBParams::GeometryCylinder)
                    ? 1
                    : 0;
    amrex::Print() << "Number signed distance functions = " << n_phi
                   << std::endl;
    totalNumberVar = nmac + ndir + n_phi;
    amrex::Print() << "Total number of variables = " << totalNumberVar
                   << std::endl;
    wi_dev.resize(ndir);
    dirx_dev.resize(ndir);
    diry_dev.resize(ndir);
    dirz_dev.resize(ndir);

    amrex::Gpu::copy(amrex::Gpu::hostToDevice, wi.begin(), wi.end(),
                     wi_dev.begin());
    amrex::Gpu::copy(amrex::Gpu::hostToDevice, dirx.begin(), dirx.end(),
                     dirx_dev.begin());
    amrex::Gpu::copy(amrex::Gpu::hostToDevice, diry.begin(), diry.end(),
                     diry_dev.begin());
    amrex::Gpu::copy(amrex::Gpu::hostToDevice, dirz.begin(), dirz.end(),
                     dirz_dev.begin());

    const Geometry &geom = Geom(0);
    if (m_marker_par.geometry_type == MarkerIBParams::GeometryBox) {
      const auto problo = geom.ProbLoArray();
      const auto probhi = geom.ProbHiArray();
      if (m_marker_par.box_xhi <= m_marker_par.box_xlo) {
        m_marker_par.box_xlo = problo[0];
        m_marker_par.box_xhi = probhi[0];
      }
      if (m_marker_par.box_yhi <= m_marker_par.box_ylo) {
        m_marker_par.box_ylo = problo[1];
        m_marker_par.box_yhi = probhi[1];
      }
#if (AMREX_SPACEDIM == 3)
      if (m_marker_par.box_zhi <= m_marker_par.box_zlo) {
        m_marker_par.box_zlo = problo[2];
        m_marker_par.box_zhi = probhi[2];
      }
#endif
    }
    L0 = geom.ProbHi(0) - geom.ProbLo(0);

    T0 = L0 / U0;
  }
}

// set covered coarse cells to be the average of overlying fine cells
void AmrCoreLBM::AverageDown() {
  for (int lev = finest_level - 1; lev >= 0; --lev) {
    amrex::average_down(f_new[lev + 1], f_new[lev], geom[lev + 1], geom[lev], 0,
                        f_new[lev].nComp(), refRatio(lev));
    amrex::average_down(macro_new[lev + 1], macro_new[lev], geom[lev + 1],
                        geom[lev], 0, macro_new[lev].nComp(), refRatio(lev));
  }
}

void AmrCoreLBM::AverageDownTo(int crse_lev) {
  amrex::average_down(f_new[crse_lev + 1], f_new[crse_lev], geom[crse_lev + 1],
                      geom[crse_lev], 0, f_new[crse_lev].nComp(),
                      refRatio(crse_lev));
  amrex::average_down(macro_new[crse_lev + 1], macro_new[crse_lev],
                      geom[crse_lev + 1], geom[crse_lev], 0,
                      macro_new[crse_lev].nComp(), refRatio(crse_lev));
}

// more flexible version of AverageDown() that lets you average down across
// multiple levels

void AmrCoreLBM::FillPatchMesoscopic(int lev, amrex::Real time,
                                     amrex::MultiFab &mf, int icomp,
                                     int ncomp) {
  if (lev == 0) {
    Vector<MultiFab *> smf;
    Vector<Real> stime;
    GetDataMesoscopic(0, time, smf, stime);

    GpuBndryFuncFab<mesoscopicBcFill> gpu_bndry_func(mesoscopicBcFill{bcval});
    PhysBCFunct<GpuBndryFuncFab<mesoscopicBcFill>> physbc(
        geom[lev], bcsMesoscopic, gpu_bndry_func);

    amrex::FillPatchSingleLevel(mf, time, smf, stime, 0, icomp, ncomp,
                                geom[lev], physbc, 0);
  } else {
    Vector<MultiFab *> cmf, fmf;
    Vector<Real> ctime, ftime;
    GetDataMesoscopic(lev - 1, time, cmf, ctime);
    GetDataMesoscopic(lev, time, fmf, ftime);

    Interpolater *mapper = &cell_cons_interp;

    GpuBndryFuncFab<mesoscopicBcFill> gpu_bndry_func(mesoscopicBcFill{bcval});
    PhysBCFunct<GpuBndryFuncFab<mesoscopicBcFill>> cphysbc(
        geom[lev - 1], bcsMesoscopic, gpu_bndry_func);
    PhysBCFunct<GpuBndryFuncFab<mesoscopicBcFill>> fphysbc(
        geom[lev], bcsMesoscopic, gpu_bndry_func);

    amrex::FillPatchTwoLevels(mf, time, cmf, ctime, fmf, ftime, 0, icomp, ncomp,
                              geom[lev - 1], geom[lev], cphysbc, 0, fphysbc, 0,
                              refRatio(lev - 1), mapper, bcsMesoscopic, 0);
    // AMR stability: f_i are not conserved scalars. Interpolating them across
    // coarse-fine interfaces can introduce nonphysical ghost-cell populations.
    // Here we overwrite only ghost cells with equilibrium reconstructed from a
    // time-consistent macroscopic FillPatch.
    if (mf.nGrow() > 0 && icomp == 0 && ncomp == ndir) {
      MultiFab tmpM(mf.boxArray(), mf.DistributionMap(), nmac, mf.nGrow());
      FillPatchMacro(lev, time, tmpM, 0, nmac);

      auto const *wi_d = wi_dev.data();
      auto const *cx_d = dirx_dev.data();
      auto const *cy_d = diry_dev.data();
      auto const *cz_d = dirz_dev.data();
      const int ndir_l = ndir;

#ifdef AMREX_USE_OMP
#pragma omp parallel if (Gpu::notInLaunchRegion())
#endif
      for (MFIter mfi(mf, TilingIfNotGPU()); mfi.isValid(); ++mfi) {

        const Box &vbx = mfi.validbox();
        const Box &gbx = mfi.fabbox();

        const int ilo = vbx.smallEnd(0), ihi = vbx.bigEnd(0);
        const int jlo = vbx.smallEnd(1), jhi = vbx.bigEnd(1);
#if (AMREX_SPACEDIM == 3)
        const int klo = vbx.smallEnd(2), khi = vbx.bigEnd(2);
#else
        const int klo = 0, khi = 0;
#endif

        auto const rho = tmpM[mfi].const_array(0);
        auto const ux = tmpM[mfi].const_array(1);
        auto const uy = tmpM[mfi].const_array(2);
        auto const uz = tmpM[mfi].const_array(3);

        auto const f = mf[mfi].array();

        amrex::ParallelFor(
            gbx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
              const bool in_valid = (i >= ilo && i <= ihi) &&
                                    (j >= jlo && j <= jhi) &&
#if (AMREX_SPACEDIM == 3)
                                    (k >= klo && k <= khi);
#else
              true;
#endif

              if (!in_valid) {
                Real r = amrex::max(rho(i, j, k), amrex::Real(1.e-12));
                Real u0 = ux(i, j, k);
                Real v0 = uy(i, j, k);
                Real w0 = uz(i, j, k);
                Real u2 = u0 * u0 + v0 * v0 + w0 * w0;

                for (int q = 0; q < ndir_l; ++q) {
                  Real cu = cx_d[q] * u0 + cy_d[q] * v0 + cz_d[q] * w0;
                  Real feq =
                      wi_d[q] * r *
                      (amrex::Real(1.0) + amrex::Real(3.0) * cu + amrex::Real(4.5) * cu * cu - amrex::Real(1.5) * u2);
                  f(i, j, k, q) = feq;
                }
              }
            });
      }
    }
  }
}

void AmrCoreLBM::FillCoarsePatchMesoscopic(int lev, amrex::Real time,
                                           amrex::MultiFab &mf, int icomp,
                                           int ncomp) {
  BL_ASSERT(lev > 0);

  Vector<MultiFab *> cmf;
  Vector<Real> ctime;
  GetDataMesoscopic(lev - 1, time, cmf, ctime);
  Interpolater *mapper = &cell_cons_interp;

  if (cmf.size() != 1) {
    amrex::Abort("FillCoarsePatchMesoscopic: how did this happen?");
  }

  GpuBndryFuncFab<mesoscopicBcFill> gpu_bndry_func(mesoscopicBcFill{bcval});
  PhysBCFunct<GpuBndryFuncFab<mesoscopicBcFill>> cphysbc(
      geom[lev - 1], bcsMesoscopic, gpu_bndry_func);
  PhysBCFunct<GpuBndryFuncFab<mesoscopicBcFill>> fphysbc(
      geom[lev], bcsMesoscopic, gpu_bndry_func);

  amrex::InterpFromCoarseLevel(mf, time, *cmf[0], 0, icomp, ncomp,
                               geom[lev - 1], geom[lev], cphysbc, 0, fphysbc, 0,
                               refRatio(lev - 1), mapper, bcsMesoscopic, 0);
}

// utility to copy in data from phi_old and/or phi_new into another multifab
void AmrCoreLBM::GetDataMesoscopic(int lev, amrex::Real time,
                                   amrex::Vector<amrex::MultiFab *> &data,
                                   amrex::Vector<amrex::Real> &datatime) {
  data.clear();
  datatime.clear();

  // Handle uninitialized old-time (you set t_old = time - 1.e200 on new levels)
  // In that case, only "new" data is meaningful.
  if (t_old[lev] < -amrex::Real(1.e100)) {
    data.push_back(&f_new[lev]);
    datatime.push_back(t_new[lev]);
    return;
  }

  const amrex::Real dtloc = t_new[lev] - t_old[lev];
  const amrex::Real teps =
      amrex::max(amrex::Real(1.e-12), amrex::Math::abs(dtloc) * amrex::Real(1.e-3));

  if (time >= t_new[lev] - teps && time <= t_new[lev] + teps) {
    data.push_back(&f_new[lev]);
    datatime.push_back(t_new[lev]);
  } else if (time >= t_old[lev] - teps && time <= t_old[lev] + teps) {
    data.push_back(&f_old[lev]);
    datatime.push_back(t_old[lev]);
  } else {
    data.push_back(&f_old[lev]);
    data.push_back(&f_new[lev]);
    datatime.push_back(t_old[lev]);
    datatime.push_back(t_new[lev]);
  }
}

// Advance a level by dt
// (includes a recursive call for finer levels)
void AmrCoreLBM::timeStepWithSubcycling(int lev, Real time, int iteration) {

  if (regrid_int > 0) // We may need to regrid
  {

    // help keep track of whether a level was already regridded
    // from a coarser level call to regrid
    static Vector<int> last_regrid_step(max_level + 1, 0);

    // regrid changes level "lev+1" so we don't regrid on max_level
    // also make sure we don't regrid fine levels again if
    // it was taken care of during a coarser regrid
    if (lev < max_level && istep[lev] > last_regrid_step[lev]) {
      if (istep[lev] % regrid_int == 0) {
        // regrid could add newly refine levels (if finest_level < max_level)
        // so we save the previous finest level index
        int old_finest = finest_level;
        regrid(lev, time);

        // mark that we have regridded this level already
        for (int k = lev; k <= finest_level; ++k) {
          last_regrid_step[k] = istep[k];
        }

        // if there are newly created levels, set the time step
        for (int k = old_finest + 1; k <= finest_level; ++k) {
          dt[k] = dt[k - 1] / MaxRefRatio(k - 1);
        }
      }
    }
  }

  if (Verbose()) {
    amrex::Print() << "[Level " << lev << " step " << istep[lev] + 1 << "] ";
    amrex::Print() << "ADVANCE with time = " << t_new[lev]
                   << " dt = " << dt[lev] << std::endl;
  }

  // Advance a single level for a single time step, and update flux registers

  t_old[lev] = t_new[lev];
  t_new[lev] += dt[lev];

  AdvancePhiAtLevel(lev, time, dt[lev], iteration, nsubsteps[lev]);

  ++istep[lev];

  if (Verbose()) {
    amrex::Print() << "[Level " << lev << " step " << istep[lev] << "] ";
    amrex::Print() << "Advanced " << CountCells(lev) << " cells" << std::endl;
  }

  if (lev < finest_level) {
    // recursive call for next-finer level
    for (int i = 1; i <= nsubsteps[lev + 1]; ++i) {
      timeStepWithSubcycling(lev + 1, time + (i - 1) * dt[lev + 1], i);
    }

    AverageDownTo(lev); // average lev+1 down to lev
    // AverageDown updates rho/u/v(/w) on the coarse level. Refresh derived
    // diagnostics afterwards so plotfile output remains consistent with the
    // velocity field after coarse-fine synchronization.
    UpdateDerivedMacroFields(lev, t_new[lev]);
  }
}

void AmrCoreLBM::InitEquilibrium() {

  // Device-accessible stencil data
  auto const *wi_d = wi_dev.data();
  auto const *cx_d = dirx_dev.data();
  auto const *cy_d = diry_dev.data();
  auto const *cz_d = dirz_dev.data();
  const int ndir_l = ndir;

  for (int lev = finest_level; lev >= 0; --lev) {
    MultiFab &curF = f_new[lev];
    MultiFab &curFo = f_old[lev];
    MultiFab &curMacro = macro_new[lev];

#ifdef AMREX_USE_OMP
#pragma omp parallel if (Gpu::notInLaunchRegion())
#endif
    for (MFIter mfi(curF, TilingIfNotGPU()); mfi.isValid(); ++mfi) {

      const Box &bx = mfi.fabbox();

      auto const rho = curMacro[mfi].const_array(0);
      auto const ux = curMacro[mfi].const_array(1);
      auto const uy = curMacro[mfi].const_array(2);
      auto const uz = curMacro[mfi].const_array(3);

      auto const f = curF[mfi].array();
      auto const fo = curFo[mfi].array();

      amrex::ParallelFor(bx, [=] AMREX_GPU_DEVICE(int i, int j,
                                                  int k) noexcept {
        Real r = amrex::max(rho(i, j, k), amrex::Real(1.e-12));
        Real u0 = ux(i, j, k);
        Real v0 = uy(i, j, k);
        Real w0 = uz(i, j, k);
        Real u2 = u0 * u0 + v0 * v0 + w0 * w0;

        for (int q = 0; q < ndir_l; ++q) {
          Real cu = cx_d[q] * u0 + cy_d[q] * v0 + cz_d[q] * w0;
          Real feq = wi_d[q] * r *
                     (amrex::Real(1.0) + amrex::Real(3.0) * cu + amrex::Real(4.5) * cu * cu - amrex::Real(1.5) * u2);
          f(i, j, k, q) = feq;
          fo(i, j, k, q) = feq;
        }
      });
    }
  }
}

void AmrCoreLBM::FillPatchMacro(int lev, amrex::Real time, amrex::MultiFab &mf,
                                int icomp, int ncomp) {

  if (lev == 0) {
    Vector<MultiFab *> smf;
    Vector<Real> stime;
    GetDataMacro(0, time, smf, stime);

    GpuBndryFuncFab<macroBcFill> gpu_bndry_func(macroBcFill{bcval});
    PhysBCFunct<GpuBndryFuncFab<macroBcFill>> physbc(geom[lev], bcsMacro,
                                                     gpu_bndry_func);

    amrex::FillPatchSingleLevel(mf, time, smf, stime, 0, icomp, ncomp,
                                geom[lev], physbc, 0);
  } else {
    Vector<MultiFab *> cmf, fmf;
    Vector<Real> ctime, ftime;
    GetDataMacro(lev - 1, time, cmf, ctime);
    GetDataMacro(lev, time, fmf, ftime);

    Interpolater *mapper = &cell_cons_interp;

    GpuBndryFuncFab<macroBcFill> gpu_bndry_func(macroBcFill{bcval});
    PhysBCFunct<GpuBndryFuncFab<macroBcFill>> cphysbc(geom[lev - 1], bcsMacro,
                                                      gpu_bndry_func);
    PhysBCFunct<GpuBndryFuncFab<macroBcFill>> fphysbc(geom[lev], bcsMacro,
                                                      gpu_bndry_func);

    amrex::FillPatchTwoLevels(mf, time, cmf, ctime, fmf, ftime, 0, icomp, ncomp,
                              geom[lev - 1], geom[lev], cphysbc, 0, fphysbc, 0,
                              refRatio(lev - 1), mapper, bcsMacro, 0);
  }
}

void AmrCoreLBM::FillPatchForcing(int lev, amrex::Real time,
                                  amrex::MultiFab &mf, int icomp, int ncomp) {
  // Just copy from current forcing[lev]; no time interpolation
  amrex::Vector<amrex::MultiFab *> smf(1, &forcing[lev]);
  amrex::Vector<amrex::Real> stime(1, t_new[lev]);

  GpuBndryFuncFab<macroBcFill> gpu_bndry_func(macroBcFill{bcval});
  PhysBCFunct<GpuBndryFuncFab<macroBcFill>> physbc(geom[lev], bcsMacro,
                                                   gpu_bndry_func);

  amrex::FillPatchSingleLevel(mf, time, smf, stime, 0, icomp, ncomp, geom[lev],
                              physbc, 0);
}

void AmrCoreLBM::FillCoarsePatchMacro(int lev, amrex::Real time,
                                      amrex::MultiFab &mf, int icomp,
                                      int ncomp) {
  BL_ASSERT(lev > 0);

  Vector<MultiFab *> cmf;
  Vector<Real> ctime;
  GetDataMacro(lev - 1, time, cmf, ctime);
  Interpolater *mapper = &cell_cons_interp;

  if (cmf.size() != 1) {
    amrex::Abort("FillCoarsePatchMacro: how did this happen?");
  }

  GpuBndryFuncFab<macroBcFill> gpu_bndry_func(macroBcFill{bcval});
  PhysBCFunct<GpuBndryFuncFab<macroBcFill>> cphysbc(geom[lev - 1], bcsMacro,
                                                    gpu_bndry_func);
  PhysBCFunct<GpuBndryFuncFab<macroBcFill>> fphysbc(geom[lev], bcsMacro,
                                                    gpu_bndry_func);

  amrex::InterpFromCoarseLevel(mf, time, *cmf[0], 0, icomp, ncomp,
                               geom[lev - 1], geom[lev], cphysbc, 0, fphysbc, 0,
                               refRatio(lev - 1), mapper, bcsMacro, 0);
}

void AmrCoreLBM::GetDataMacro(int lev, Real time, Vector<MultiFab *> &data,
                              Vector<Real> &datatime) {
  data.clear();
  datatime.clear();

  // Handle uninitialized/sentinel time (e.g. t_old = time - 1.e200 on new
  // levels). In that case, only the "new" state is meaningful.
  constexpr Real SENT = amrex::Real(1.e50);
  if (amrex::Math::abs(t_old[lev]) > SENT ||
      amrex::Math::abs(t_new[lev]) > SENT) {
    data.push_back(&macro_new[lev]);
    datatime.push_back(t_new[lev]);
    return;
  }

  const Real dtloc = amrex::Math::abs(t_new[lev] - t_old[lev]);
  const Real teps = amrex::max(amrex::Real(1.e-12), dtloc * amrex::Real(1.e-3));

  if (time >= t_new[lev] - teps && time <= t_new[lev] + teps) {
    data.push_back(&macro_new[lev]);
    datatime.push_back(t_new[lev]);
  } else if (time >= t_old[lev] - teps && time <= t_old[lev] + teps) {
    data.push_back(&macro_old[lev]);
    datatime.push_back(t_old[lev]);
  } else {
    data.push_back(&macro_old[lev]);
    data.push_back(&macro_new[lev]);
    datatime.push_back(t_old[lev]);
    datatime.push_back(t_new[lev]);
  }
}

void AmrCoreLBM::BuildLevelSetOnLevel(int lev) {
  const bool marker_levelset_ibm =
      (m_ib_method != IBMMethodMarker ||
       m_marker_par.geometry_type == MarkerIBParams::GeometryCylinder);
  if (!m_use_cylinder || !m_ls || !marker_levelset_ibm)
    return;

  // Use the *macro* MultiFab as the reference for BA/DM
  const BoxArray &ba = macro_new[lev].boxArray();
  const DistributionMapping &dm = macro_new[lev].DistributionMap();
  amrex::Print() << "BuildLevelSetOnLevel: level " << lev
                 << " (nghost = " << nghost << ")\n";
  // (Re)define storage for this level and rebuild φ
  m_ls->define_level(lev, ba, dm, /*ng=*/nghost);
  m_ls->build_from_cylinder(lev, geom[lev], m_ls_par);

  amrex::Print() << "BuildLevelSetOnLevel: level " << lev
                 << " (|BA| = " << ba.size() << ", R = " << m_ls_par.R << ")\n";
}
