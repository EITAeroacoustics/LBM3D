#include <AmrCoreLBM.H>
#include "IBM/IBMarkerDF.H"
#include "IBM/IBForceEval.H"

#include <AMReX_ParallelDescriptor.H>

#include <fstream>
#include <iomanip>

using namespace amrex;

void AmrCoreLBM::ComputeIBForce(Real time, int step) {
  if (!m_use_cylinder) {
    return; // no IBM
  }

  const int lev = finestLevel(); // IBM is active only on finest level
  if (lev < 0)
    return;

  if (lev >= static_cast<int>(forcing.size())) {
    return;
  }

  if (forcing[lev].nComp() < AMREX_SPACEDIM) {
    return;
  }

  // --------------------------------------------------------------------
  // 1) Force on body from IBM coupling (all diagnostics)
  // --------------------------------------------------------------------
  Real Fx_eul = amrex::Real(0.0), Fy_eul = amrex::Real(0.0), Fz_eul = amrex::Real(0.0);
  Real Fx_marker = amrex::Real(0.0), Fy_marker = amrex::Real(0.0), Fz_marker = amrex::Real(0.0);
  Real Fx_me = amrex::Real(0.0), Fy_me = amrex::Real(0.0), Fz_me = amrex::Real(0.0);

  const Real dt_lev = dt[lev];

  // Eulerian body force recovered from the LBM forcing field actually coupled
  // into the solve.
  //
  // forcing[lev] stores the Guo source in lattice form, i.e.
  //   (dt * force_density)
  // so the domain integral must be divided by dt_lev to recover a force-like
  // quantity that is comparable across AMR levels and with the marker sum.
  {
    const amrex::Box &domain = geom[lev].Domain();
    Real Fx_sum = forcing[lev].sum(domain, 0, false);
    Real Fy_sum = forcing[lev].sum(domain, 1, false);
#if (AMREX_SPACEDIM == 3)
    Real Fz_sum = forcing[lev].sum(domain, 2, false);
#else
    Real Fz_sum = 0.0;
#endif
    const auto dx = geom[lev].CellSizeArray();
    Real dV = dx[0];
#if (AMREX_SPACEDIM >= 2)
    dV *= dx[1];
#endif
#if (AMREX_SPACEDIM == 3)
    dV *= dx[2];
#endif
    Fx_eul = -(Fx_sum * dV) / dt_lev;
    Fy_eul = -(Fy_sum * dV) / dt_lev;
    Fz_eul = -(Fz_sum * dV) / dt_lev;
  }

  // Marker force integral from Lagrangian direct-forcing data. The marker
  // backend stores acceleration-like forcing, so this sum is already in the
  // same per-time-step units as the dt-corrected Eulerian force above.
  if (m_ib_method == IBMMethodMarker && m_ibm) {
    auto Fm = m_ibm->last_marker_force_sum();
    Fx_marker = -Fm[0];
    Fy_marker = -Fm[1];
    Fz_marker = -Fm[2];
  }

  // Link-wise momentum exchange is only meaningful when solid-side
  // populations are actually part of the boundary model. For the current
  // marker direct-forcing IBM, the robust body-force diagnostic is the
  // Eulerian forcing integral, while the raw marker-force integral remains
  // available separately as a Lagrangian consistency diagnostic.
  Fx_me = Fx_eul;
  Fy_me = Fy_eul;
  Fz_me = Fz_eul;
  if (m_ib_method != IBMMethodMarker) {
    auto Fme = IBForceEval::ComputeMomentumExchangeBodyForce(
        f_new[lev], geom[lev], dirx, diry, dirz, ndir, m_ls_par, false);
    Fx_me = Fme[0];
    Fy_me = Fme[1];
    Fz_me = Fme[2];
  } else if (m_force_eval_method == ForceEvalMomentumExchange) {
    static bool warned_marker_me_fallback = false;
    if (!warned_marker_me_fallback && amrex::ParallelDescriptor::IOProcessor()) {
      warned_marker_me_fallback = true;
      amrex::Print()
          << "NOTE: ibm.force_eval_method = momentum_exchange falls back to "
             "the Eulerian IBM-force integral for marker IBM. "
             "The raw marker-force sum is still reported separately.\n";
    }
  }

  Real Fx_body = Fx_eul;
  Real Fy_body = Fy_eul;
  Real Fz_body = Fz_eul;
  if (m_force_eval_method == ForceEvalMarker) {
    Fx_body = Fx_marker;
    Fy_body = Fy_marker;
    Fz_body = Fz_marker;
  } else if (m_force_eval_method == ForceEvalMomentumExchange) {
    Fx_body = Fx_me;
    Fy_body = Fy_me;
    Fz_body = Fz_me;
  }

  // Time-centered body force for Guo-forced LBM diagnostics:
  // use midpoint (n+1/2) estimate from consecutive whole-step forces.
  Real Fx_body_tc = Fx_body;
  Real Fy_body_tc = Fy_body;
  Real Fz_body_tc = Fz_body;
  if (m_have_prev_body_force) {
    Fx_body_tc = amrex::Real(0.5) * (m_prev_body_force[0] + Fx_body);
    Fy_body_tc = amrex::Real(0.5) * (m_prev_body_force[1] + Fy_body);
    Fz_body_tc = amrex::Real(0.5) * (m_prev_body_force[2] + Fz_body);
  }
  m_prev_body_force[0] = Fx_body;
  m_prev_body_force[1] = Fy_body;
  m_prev_body_force[2] = Fz_body;
  m_have_prev_body_force = true;
#if (AMREX_SPACEDIM != 3)
  amrex::ignore_unused(Fz_body_tc);
#endif

  // --------------------------------------------------------------------
  // 2) Force coefficients
  //
  // In 2D, use the usual cylinder normalization with reference length D.
  // In 3D, use the frontal area A = pi R^2.
  //
  //   2D: Cx = Fx / (0.5 * rho_ref * U_ref^2 * D)
  //   3D: Cx = Fx / (0.5 * rho_ref * U_ref^2 * A)
  //
  // The second reported coefficient keeps the historical "Cl" column name,
  // but in 3D it is simply the y-direction lateral-force coefficient.
  // --------------------------------------------------------------------
  Real rho_ref = amrex::Real(1.0);            // standard LBM choice
  Real U_ref = U0;                  // set earlier in ReadParameters()
  Real D_ref = amrex::Real(2.0) * m_ls_par.R; // cylinder diameter

  Real Cd = amrex::Real(0.0), Cl = amrex::Real(0.0);
  Real Cd_raw = amrex::Real(0.0), Cl_raw = amrex::Real(0.0);
  Real Cd_eul = amrex::Real(0.0), Cl_eul = amrex::Real(0.0);
  Real Cd_marker = amrex::Real(0.0), Cl_marker = amrex::Real(0.0);
  Real Cd_me = amrex::Real(0.0), Cl_me = amrex::Real(0.0);
#if (AMREX_SPACEDIM == 3)
  Real Cz = amrex::Real(0.0);
  Real Cz_raw = amrex::Real(0.0);
  Real Cz_eul = amrex::Real(0.0);
  Real Cz_marker = amrex::Real(0.0);
  Real Cz_me = amrex::Real(0.0);
#endif

  Real denom = amrex::Real(0.0);
#if (AMREX_SPACEDIM == 3)
  const Real A_ref = Math::pi<Real>() * m_ls_par.R * m_ls_par.R;
  denom = amrex::Real(0.5) * rho_ref * U_ref * U_ref * A_ref;
#else
  denom = amrex::Real(0.5) * rho_ref * U_ref * U_ref * D_ref;
#endif
  if (denom > amrex::Real(0.0)) {
    Cd_raw = Fx_body / denom;
    Cl_raw = Fy_body / denom;
    Cd = Fx_body_tc / denom;
    Cl = Fy_body_tc / denom;
    Cd_eul = Fx_eul / denom;
    Cl_eul = Fy_eul / denom;
    Cd_marker = Fx_marker / denom;
    Cl_marker = Fy_marker / denom;
    Cd_me = Fx_me / denom;
    Cl_me = Fy_me / denom;
#if (AMREX_SPACEDIM == 3)
    Cz_raw = Fz_body / denom;
    Cz = Fz_body_tc / denom;
    Cz_eul = Fz_eul / denom;
    Cz_marker = Fz_marker / denom;
    Cz_me = Fz_me / denom;
#endif
  }

  // --------------------------------------------------------------------
  // 3) Print + append everything to force.dat
  // --------------------------------------------------------------------
  if (amrex::ParallelDescriptor::IOProcessor()) {

    if (!m_force_output_initialized) {
      m_force_ofs.open(m_force_file);
      if (!m_force_ofs) {
        amrex::Print() << "WARNING: could not open " << m_force_file << "\n";
        return;
      }
#if (AMREX_SPACEDIM == 3)
      m_force_ofs << "# 3D coefficients are normalized by frontal area A = pi R^2.\n";
      m_force_ofs << "# In 3D, the historical Cl columns represent the y-force coefficient.\n";
      m_force_ofs << "# Additional z-force and Cz columns are appended after t_conv.\n";
#else
      m_force_ofs << "# 2D coefficients are normalized by reference length D = 2R.\n";
#endif
      m_force_ofs << "# step  time  Fx_body_tc  Fy_body_tc  Cd  Cl"
                     "  Fx_body_raw  Fy_body_raw  Cd_raw  Cl_raw"
                     "  Fx_eul  Fy_eul  Cd_eul  Cl_eul"
                     "  Fx_marker  Fy_marker  Cd_marker  Cl_marker"
                     "  Fx_me  Fy_me  Cd_me  Cl_me  t_conv";
#if (AMREX_SPACEDIM == 3)
      m_force_ofs << "  Fz_body_tc  Cz"
                     "  Fz_body_raw  Cz_raw"
                     "  Fz_eul  Cz_eul"
                     "  Fz_marker  Cz_marker"
                     "  Fz_me  Cz_me";
#endif
      m_force_ofs << "\n";
      m_force_output_initialized = true;
    }

    const Real t_conv = (D_ref > amrex::Real(0.0))
                            ? (time * U_ref / D_ref)
                            : amrex::Real(0.0);

    m_force_ofs << step << "  " << time << "  "
                << Fx_body_tc << "  " << Fy_body_tc << "  " << Cd << "  "
                << Cl << "  " << Fx_body << "  " << Fy_body << "  "
                << Cd_raw << "  " << Cl_raw << "  " << Fx_eul << "  "
                << Fy_eul << "  " << Cd_eul << "  " << Cl_eul << "  "
                << Fx_marker << "  " << Fy_marker << "  " << Cd_marker << "  "
                << Cl_marker << "  " << Fx_me << "  " << Fy_me << "  "
                << Cd_me << "  " << Cl_me << "  " << t_conv;
#if (AMREX_SPACEDIM == 3)
    m_force_ofs << "  " << Fz_body_tc << "  " << Cz << "  " << Fz_body
                << "  " << Cz_raw << "  " << Fz_eul << "  " << Cz_eul
                << "  " << Fz_marker << "  " << Cz_marker << "  " << Fz_me
                << "  " << Cz_me;
#endif
    m_force_ofs << "\n";
    m_force_ofs.flush();

    if (m_force_eval_debug > 0) {
      amrex::Print() << "[force_eval] step=" << step
                     << " primary(" << m_force_eval_method << "): Cd=" << Cd
                     << " Cl=" << Cl
#if (AMREX_SPACEDIM == 3)
                     << " Cz=" << Cz
#endif
                     << " (raw Cd,Cl)=(" << Cd_raw << "," << Cl_raw << ")"
                     << " | eulerian(Cd,Cl)=(" << Cd_eul << "," << Cl_eul
                     << ") marker=(" << Cd_marker << "," << Cl_marker << ")"
                     << " me=(" << Cd_me << "," << Cl_me << ")\n";
    }
  }
}
