#ifndef LBM3D_PROBLEM_INIT_H_
#define LBM3D_PROBLEM_INIT_H_

#include <AMReX_Geometry.H>
#include <AMReX_MultiFab.H>

// Host entry point supplied by each example; the example launches its own
// GPU initial-field kernel. No host function pointer enters device code.
using ProblemInit = void (*)(amrex::MultiFab&, amrex::Geometry const&,
                             amrex::Real);

#endif
