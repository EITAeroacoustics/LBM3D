#include <AMReX_REAL.H>

#ifdef LBM_UPSTREAM_GEOMETRY
#include <IBMUserDefinedGeometry.H>
#else
#include <PitchingAirfoilGeometry.H>
#endif

#include <iomanip>
#include <iostream>

int main()
{
    MarkerIBParams par;
    const amrex::Real x_ref[] = {-5.0, 3.0};
    const amrex::Real y_ref[] = {0.0, 1.0};
    const amrex::Real z_ref[] = {0.0, 0.0};
    std::cout << std::setprecision(17);
    for (amrex::Real time : {amrex::Real(0), amrex::Real(1), amrex::Real(2)}) {
        for (int idx = 0; idx < 2; ++idx) {
            amrex::Real x, y, z, ux, uy, uz;
            lbm_user_ibm_geometry::marker_state(idx, time, par, 96.0, 96.0, 0.0,
                                                 x_ref, y_ref, z_ref,
                                                 x, y, z, ux, uy, uz);
            std::cout << "MOTION idx=" << idx << " time=" << time
                      << " x=" << x << " y=" << y << " z=" << z
                      << " ux=" << ux << " uy=" << uy << " uz=" << uz << '\n';
        }
    }
}
