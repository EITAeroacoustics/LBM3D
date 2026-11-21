#include <cstdint>
#include <cstring>
#include <iomanip>

#include <AMReX.H>
#include <AMReX_MultiFab.H>
#include <AMReX_ParReduce.H>
#include <AMReX_ParallelContext.H>
#include <AMReX_ParallelDescriptor.H>
#include <AMReX_Print.H>

#include <AmrCoreLBM.H>
#include <ProblemInit.H>

void InitializeProblem(amrex::MultiFab& macro, amrex::Geometry const& geom,
                       amrex::Real nu);

namespace {

AMREX_GPU_HOST_DEVICE AMREX_FORCE_INLINE
std::uint64_t value_bits(amrex::Real value) noexcept {
  const double number = static_cast<double>(value);
#if defined(__CUDA_ARCH__)
  return static_cast<std::uint64_t>(__double_as_longlong(number));
#else
  std::uint64_t bits;
  std::memcpy(&bits, &number, sizeof(bits));
  return bits;
#endif
}

AMREX_GPU_HOST_DEVICE AMREX_FORCE_INLINE
std::uint64_t field_hash(amrex::Real value, int i, int j, int k,
                         int comp) noexcept {
  std::uint64_t hash = value_bits(value);
  hash ^= static_cast<std::uint64_t>(static_cast<std::uint32_t>(i)) *
          0x9e3779b185ebca87ULL;
  hash ^= static_cast<std::uint64_t>(static_cast<std::uint32_t>(j)) *
          0xc2b2ae3d27d4eb4fULL;
  hash ^= static_cast<std::uint64_t>(static_cast<std::uint32_t>(k)) *
          0x165667b19e3779f9ULL;
  hash ^= static_cast<std::uint64_t>(comp) * 0x85ebca77c2b2ae63ULL;
  hash ^= hash >> 33;
  hash *= 0xff51afd7ed558ccdULL;
  hash ^= hash >> 33;
  hash *= 0xc4ceb9fe1a85ec53ULL;
  return hash ^ (hash >> 33);
}

} // namespace

int main(int argc, char* argv[]) {
  amrex::Initialize(argc, argv);
  {
    AmrCoreLBM solver(InitializeProblem);
    solver.InitData();
    solver.Evolve();

    // Reduce the final fields in memory; no plotfile or checkpoint is written.
    auto fields = solver.PlotFileMF();
    for (int lev = 0; lev < static_cast<int>(fields.size()); ++lev) {
      auto const& field = *fields[lev];
      for (int comp = 0; comp < field.nComp(); ++comp) {
        // Derived vorticity and pressure are refreshed only for output/regrid.
        if (comp == 4 || comp == 5) {
          continue;
        }
        const auto sum = field.sum(comp);
        const auto norm2 = field.norm2(comp);
        const auto min = field.min(comp);
        const auto max = field.max(comp);
        auto const arrays = field.const_arrays();
        // Coordinate and value bits make this compact check sensitive to
        // misplaced populations; split the hash into bounded integer sums.
        auto const fingerprint = amrex::ParReduce(
            amrex::TypeList<amrex::ReduceOpSum, amrex::ReduceOpSum>{},
            amrex::TypeList<unsigned long long, unsigned long long>{},
            field, amrex::IntVect(0),
            [=] AMREX_GPU_DEVICE(int box, int i, int j, int k) noexcept
                -> amrex::GpuTuple<unsigned long long, unsigned long long> {
              const auto hash = field_hash(arrays[box](i, j, k, comp),
                                           i, j, k, comp);
              return {hash & 0xffffffffULL, hash >> 32};
            });
        unsigned long long hashes[2] = {amrex::get<0>(fingerprint),
                                        amrex::get<1>(fingerprint)};
#ifdef AMREX_USE_MPI
        BL_MPI_REQUIRE(MPI_Allreduce(MPI_IN_PLACE, hashes, 2,
                                     MPI_UNSIGNED_LONG_LONG, MPI_SUM,
                                     amrex::ParallelContext::CommunicatorSub()));
#endif
        amrex::Print() << std::setprecision(17)
                       << "FIELD_SUMMARY lev=" << lev << " comp=" << comp
                       << " sum=" << sum << " norm2=" << norm2
                       << " min=" << min << " max=" << max
                       << " hash0=" << hashes[0] << " hash1=" << hashes[1]
                       << '\n';
      }
    }
  }
  amrex::Finalize();
}
