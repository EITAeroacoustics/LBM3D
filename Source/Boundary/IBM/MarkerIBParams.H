#pragma once

#include <AMReX_REAL.H>

// Parameters for IAMReX-style marker-based direct-forcing IBM.
//
// This is intentionally kept as a POD to simplify I/O via ParmParse.
struct MarkerIBParams {
  enum CouplingMethod {
    CouplingExplicit = 0,
    CouplingIVC = 1,
    CouplingExplicitDiag = 2
  };

  // Marker-fluid coupling strategy:
  //   explicit : IAMReX-style multi-direct-forcing loop
  //   ivc      : implicit velocity correction (Wu & Shu style)
  // Default to IVC for sphere IBM runs; explicit remains available for
  // diagnostics/regression checks.
  int coupling_method{CouplingIVC};

  // Discrete delta kernel type (matches IAMReX enum ordering)
  //   0 = FOUR_POINT_IB
  //   1 = THREE_POINT_IB
  int delta_type{0};

  // Number of multi-direct-forcing iterations (IAMReX: loop_ns / loop_solid)
  int loop_ns{2};

  // Under-relaxation for explicit MDF updates.
  // 1.0 reproduces the current explicit forcing:
  //   F_k = (U_b - U_k)/dt.
  // Values in (0,1] can improve fixed-point stability for iterative MDF.
  amrex::Real mdf_relax{1.0};

  // For CouplingExplicitDiag, use a diagonal implicit correction:
  //   F_k = (U_b - U_k) / (dt * M_kk),  M_kk = dv * sum(delta_h^2 dV)
  // This is a Jacobi approximation of the Wu-Shu IVC linear system.
  // The epsilon is a numerical floor on M_kk.
  amrex::Real explicit_diag_eps{1.0e-8};

  // Optional override for number of Lagrangian markers.
  // If 0, a heuristic is used (IAMReX-like for spheres).
  int n_marker{0};

  // Optional AMR refinement envelope around spherical IBM bodies,
  // expressed in multiples of the body radius.
  // If <= 0, the legacy body-only refinement box is used.
  amrex::Real refine_upstream{-1.0};
  amrex::Real refine_downstream{-1.0};
  amrex::Real refine_cross{-1.0};

  // IAMReX 'rd' parameter used in their Ml/dv formula for spherical shells.
  // (Defaults to 0.0; keep it configurable for reproducibility.)
  amrex::Real rd{0.0};

  // Rigid-body kinematics (prescribed here; your code currently uses a fixed
  // body).
  amrex::Real ubx{0.0};
  amrex::Real uby{0.0};
  amrex::Real ubz{0.0};
  amrex::Real omx{0.0};
  amrex::Real omy{0.0};
  amrex::Real omz{0.0};

  // Diagnostics
  int verbose{0};

  // IVC linear system regularization term (added to diagonal).
  amrex::Real ivc_diag_reg{1.0e-12};

  // If >0, rebuild the IVC coupling operator each time step.
  // For stationary rigid bodies this should stay 0.
  int ivc_rebuild_matrix{0};

  // If >0, print IVC matrix/solve diagnostics.
  int ivc_verbose{0};

  // -------------------------------
  // Optional debug & consistency controls
  // -------------------------------

  // If >0, print global marker-vs-Euler force balance each MDF iteration.
  // (Sum over markers of F*dv should match sum over grid of f*dV.)
  int debug_force_balance{0};

  // If >0, print min/mean/max kernel partition (sum(delta*dV)) over markers.
  int debug_kernel_partition{0};

  // If >0, renormalize the kernel locally so that sum(delta*dV)==1.
  // This is useful near physical boundaries and (depending on implementation)
  // near coarse-fine interfaces.
  int renormalize_delta{0};

};
