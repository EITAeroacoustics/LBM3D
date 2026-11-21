#include <AMReX.H>
#include <AMReX_Arena.H>
#include <AMReX_Gpu.H>
#include <AMReX_MultiFab.H>
#include <AMReX_ParallelDescriptor.H>
#include <AMReX_PlotFileUtil.H>
#include <AMReX_Print.H>

#include <cstdint>
#include <cstring>
#include <string>

int main(int argc, char* argv[])
{
    amrex::Initialize(argc, argv, false);
    int status = 0;
    {
        if (amrex::command_argument_count() != 2) {
            amrex::Abort("usage: tgv3d_compare REFERENCE_PLOTFILE OTHER_PLOTFILE");
        }
        amrex::PlotFileData reference(amrex::get_command_argument(1));
        amrex::PlotFileData other(amrex::get_command_argument(2));
        if (reference.finestLevel() != 0 || other.finestLevel() != 0 ||
            reference.probDomain(0) != other.probDomain(0) ||
            reference.levelStep(0) != other.levelStep(0)) {
            amrex::Abort("plotfiles have different grid or output step");
        }

        for (auto const& name : {"rho", "ux", "uy", "uz"}) {
            auto left = reference.get(0, name);
            auto right = other.get(0, name);
            amrex::MultiFab host_left(reference.boxArray(0), reference.DistributionMap(0),
                                      1, 0, amrex::MFInfo().SetArena(amrex::The_Pinned_Arena()));
            amrex::MultiFab host_right(reference.boxArray(0), reference.DistributionMap(0),
                                       1, 0, amrex::MFInfo().SetArena(amrex::The_Pinned_Arena()));
            host_left.ParallelCopy(left, 0, 0, 1);
            host_right.ParallelCopy(right, 0, 0, 1);
            amrex::Gpu::streamSynchronize();
            amrex::Long mismatches = 0;
            int first_i = -1, first_j = -1, first_k = -1;
            for (amrex::MFIter mfi(host_left); mfi.isValid(); ++mfi) {
                const auto a = host_left.const_array(mfi);
                const auto b = host_right.const_array(mfi);
                const auto box = mfi.validbox();
                const auto lo = amrex::lbound(box);
                const auto hi = amrex::ubound(box);
                for (int k = lo.z; k <= hi.z; ++k) {
                    for (int j = lo.y; j <= hi.y; ++j) {
                        for (int i = lo.x; i <= hi.x; ++i) {
                            std::uint64_t bits_a, bits_b;
                            const double value_a = a(i,j,k);
                            const double value_b = b(i,j,k);
                            std::memcpy(&bits_a, &value_a, sizeof(bits_a));
                            std::memcpy(&bits_b, &value_b, sizeof(bits_b));
                            if (bits_a != bits_b) {
                                ++mismatches;
                                if (first_i < 0) {
                                    first_i = i; first_j = j; first_k = k;
                                }
                            }
                        }
                    }
                }
            }
            amrex::ParallelDescriptor::ReduceLongSum(mismatches);
            amrex::Print() << "BIT_COMPARE var=" << name
                           << " mismatches=" << mismatches
                           << " first_local=(" << first_i << ',' << first_j << ','
                           << first_k << ")\n";
            if (mismatches) { status = 1; }
        }
    }
    amrex::Finalize();
    return status;
}
