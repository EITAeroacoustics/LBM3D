#include <AMReX.H>
#include <AMReX_Arena.H>
#include <AMReX_Gpu.H>
#include <AMReX_MultiFab.H>
#include <AMReX_ParallelDescriptor.H>
#include <AMReX_PlotFileUtil.H>
#include <AMReX_Print.H>

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <string>

int main(int argc, char* argv[])
{
    amrex::Initialize(argc, argv, false);
    {
        if (amrex::command_argument_count() != 1) {
            amrex::Abort("usage: tgv3d_analyze PLOTFILE");
        }

        amrex::PlotFileData plot(amrex::get_command_argument(1));
        if (plot.finestLevel() != 0 || plot.spaceDim() != 3) {
            amrex::Abort("TGV3D analysis expects one 3D uniform level");
        }

        const auto& names = plot.varNames();
        for (auto const& name : {"rho", "ux", "uy", "uz"}) {
            if (std::find(names.begin(), names.end(), name) == names.end()) {
                amrex::Abort(std::string("missing plot variable: ") + name);
            }
        }

        auto all = plot.get(0);
        const bool nonfinite = all.contains_nan() || all.contains_inf();
        amrex::MultiFab host(plot.boxArray(0), plot.DistributionMap(0), 4, 0,
                             amrex::MFInfo().SetArena(amrex::The_Pinned_Arena()));
        int c = 0;
        for (auto const& name : {"rho", "ux", "uy", "uz"}) {
            auto field = plot.get(0, name);
            amrex::MultiFab::Copy(host, field, 0, c++, 1, 0);
        }
        amrex::Gpu::streamSynchronize();

        const auto lo = plot.probLo();
        const auto hi = plot.probHi();
        const auto dx = plot.cellSize(0);
        const double pi = std::acos(-1.0);
        const double kx = 2.0 * pi / (hi[0] - lo[0]);
        const double ky = 2.0 * pi / (hi[1] - lo[1]);
        const double kz = 2.0 * pi / (hi[2] - lo[2]);
        constexpr double u0 = 0.02;
        double mass = 0.0;
        double kinetic = 0.0;
        double init_err = 0.0;
        for (amrex::MFIter mfi(host); mfi.isValid(); ++mfi) {
            const auto a = host.const_array(mfi);
            const auto box = mfi.validbox();
            const auto low = amrex::lbound(box);
            const auto high = amrex::ubound(box);
            for (int k = low.z; k <= high.z; ++k) {
                for (int j = low.y; j <= high.y; ++j) {
                    for (int i = low.x; i <= high.x; ++i) {
                        const double rho = a(i,j,k,0);
                        const double ux = a(i,j,k,1);
                        const double uy = a(i,j,k,2);
                        const double uz = a(i,j,k,3);
                        mass += rho;
                        kinetic += 0.5 * rho * (ux*ux + uy*uy + uz*uz);
                        if (plot.levelStep(0) == 0) {
                            const double x = lo[0] + (i+0.5)*dx[0];
                            const double y = lo[1] + (j+0.5)*dx[1];
                            const double z = lo[2] + (k+0.5)*dx[2];
                            const double expected_ux = u0*std::sin(kx*x)*std::cos(ky*y)*std::cos(kz*z);
                            const double expected_uy = -u0*std::cos(kx*x)*std::sin(ky*y)*std::cos(kz*z);
                            const double pressure = u0*u0/16.0 *
                                (std::cos(2*kx*x)+std::cos(2*ky*y)) * (std::cos(2*kz*z)+2.0);
                            const double expected_rho = 1.0 + 3.0*pressure;
                            init_err = std::max(init_err, std::abs(rho-expected_rho));
                            init_err = std::max(init_err, std::abs(ux-expected_ux));
                            init_err = std::max(init_err, std::abs(uy-expected_uy));
                            init_err = std::max(init_err, std::abs(uz));
                        }
                    }
                }
            }
        }
        amrex::ParallelDescriptor::ReduceRealSum(mass);
        amrex::ParallelDescriptor::ReduceRealSum(kinetic);
        amrex::ParallelDescriptor::ReduceRealMax(init_err);

        const auto ncell = plot.probDomain(0).numPts();
        amrex::Print() << std::setprecision(17)
            << "TGV_METRICS step=" << plot.levelStep(0)
            << " time=" << plot.time()
            << " cells=" << ncell
            << " mean_rho=" << mass / static_cast<double>(ncell)
            << " mean_kinetic=" << kinetic / static_cast<double>(ncell)
            << " init_linf=" << init_err
            << " nonfinite=" << nonfinite << '\n';
    }
    amrex::Finalize();
}
