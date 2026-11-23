#include <cstdint>
#include <cstring>
#include <iomanip>

#include <AMReX.H>
#include <AMReX_Math.H>
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

void PrintFieldSummary(amrex::MultiFab const& field, int lev,
                       int source_comp, int output_comp) {
  const auto sum = field.sum(source_comp);
  const auto norm2 = field.norm2(source_comp);
  const auto min = field.min(source_comp);
  const auto max = field.max(source_comp);
  auto const arrays = field.const_arrays();
  // Use the plotfile component number in the coordinate-sensitive hash.
  auto const fingerprint = amrex::ParReduce(
      amrex::TypeList<amrex::ReduceOpSum, amrex::ReduceOpSum>{},
      amrex::TypeList<unsigned long long, unsigned long long>{},
      field, amrex::IntVect(0),
      [=] AMREX_GPU_DEVICE(int box, int i, int j, int k) noexcept
          -> amrex::GpuTuple<unsigned long long, unsigned long long> {
        const auto hash = field_hash(arrays[box](i, j, k, source_comp),
                                     i, j, k, output_comp);
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
                 << "FIELD_SUMMARY lev=" << lev << " comp=" << output_comp
                 << " sum=" << sum << " norm2=" << norm2
                 << " min=" << min << " max=" << max
                 << " hash0=" << hashes[0] << " hash1=" << hashes[1]
                 << '\n';
}

#ifdef LBM_TGV_METRICS
void PrintTgvMetrics(AmrCoreLBM const& solver) {
  constexpr double u0 = 0.02;
  constexpr double cs2 = 1.0 / 3.0;
  int const lev = 0;
  int const step = solver.StepAtLevel(lev);
  auto const& macro = solver.MacroState(lev);
  auto const& f = solver.DistributionState(lev);
  auto const& geom = solver.Geom(lev);
  auto const prob_lo = geom.ProbLoArray();
  auto const prob_hi = geom.ProbHiArray();
  auto const dx = geom.CellSizeArray();
  double const two_pi = 2.0 * amrex::Math::pi<double>();
  double const kx = two_pi / (static_cast<double>(prob_hi[0]) - prob_lo[0]);
  double const ky = two_pi / (static_cast<double>(prob_hi[1]) - prob_lo[1]);
  double const kz = two_pi / (static_cast<double>(prob_hi[2]) - prob_lo[2]);
  auto const arrays = macro.const_arrays();
  auto const values = amrex::ParReduce(
      amrex::TypeList<amrex::ReduceOpSum, amrex::ReduceOpSum,
                      amrex::ReduceOpMax>{},
      amrex::TypeList<double, double, double>{},
      macro, amrex::IntVect(0),
      [=] AMREX_GPU_DEVICE(int box, int i, int j, int k) noexcept
          -> amrex::GpuTuple<double, double, double> {
        auto const& a = arrays[box];
        double const rho = static_cast<double>(a(i, j, k, 0));
        double const ux = static_cast<double>(a(i, j, k, 1));
        double const uy = static_cast<double>(a(i, j, k, 2));
        double const uz = static_cast<double>(a(i, j, k, 3));
        double const kinetic =
            0.5 * rho * (ux * ux + uy * uy + uz * uz);
        double error = 0.0;
        if (step == 0) {
          double const x = static_cast<double>(prob_lo[0]) +
                           (i + 0.5) * static_cast<double>(dx[0]);
          double const y = static_cast<double>(prob_lo[1]) +
                           (j + 0.5) * static_cast<double>(dx[1]);
          double const z = static_cast<double>(prob_lo[2]) +
                           (k + 0.5) * static_cast<double>(dx[2]);
          auto const sx = amrex::Math::sincos(kx * x);
          auto const sy = amrex::Math::sincos(ky * y);
          auto const sz = amrex::Math::sincos(kz * z);
          double const expected_ux =
              u0 * sx.first * sy.second * sz.second;
          double const expected_uy =
              -u0 * sx.second * sy.first * sz.second;
          double const pressure = u0 * u0 / 16.0 *
              (amrex::Math::sincos(2.0 * kx * x).second +
               amrex::Math::sincos(2.0 * ky * y).second) *
              (amrex::Math::sincos(2.0 * kz * z).second + 2.0);
          double const expected_rho = 1.0 + pressure / cs2;
          error = amrex::max(amrex::Math::abs(rho - expected_rho),
                            amrex::Math::abs(ux - expected_ux));
          error = amrex::max(error,
                             amrex::Math::abs(uy - expected_uy));
          error = amrex::max(error, amrex::Math::abs(uz));
        }
        return {rho, kinetic, error};
      });
  double sums[2] = {amrex::get<0>(values), amrex::get<1>(values)};
  double init_error = amrex::get<2>(values);
#ifdef AMREX_USE_MPI
  BL_MPI_REQUIRE(MPI_Allreduce(MPI_IN_PLACE, sums, 2, MPI_DOUBLE, MPI_SUM,
                               amrex::ParallelContext::CommunicatorSub()));
  BL_MPI_REQUIRE(MPI_Allreduce(MPI_IN_PLACE, &init_error, 1, MPI_DOUBLE,
                               MPI_MAX,
                               amrex::ParallelContext::CommunicatorSub()));
#endif
  auto const cells = geom.Domain().numPts();
  bool const nonfinite = macro.contains_nan() || macro.contains_inf() ||
                         f.contains_nan() || f.contains_inf();
  amrex::Print() << "TGV_PRECISION real_bytes=" << sizeof(amrex::Real) << '\n';
  amrex::Print() << std::setprecision(17)
                 << "TGV_METRICS step=" << step
                 << " time=" << solver.TimeAtLevel(lev)
                 << " cells=" << cells
                 << " mean_rho=" << sums[0] / static_cast<double>(cells)
                 << " mean_kinetic=" << sums[1] / static_cast<double>(cells)
                 << " init_linf=" << init_error
                 << " nonfinite=" << nonfinite << '\n';
}
#endif

int main(int argc, char* argv[]) {
  amrex::Initialize(argc, argv);
  {
    AmrCoreLBM solver(InitializeProblem);
    solver.InitData();
    solver.Evolve();

    // Reduce resident state directly. PlotFileMF would duplicate all 25
    // components and defeat single-GPU capacity measurements.
    for (int lev = 0; lev <= solver.finestLevel(); ++lev) {
      auto const& macro = solver.MacroState(lev);
      auto const& f = solver.DistributionState(lev);
      for (int comp = 0; comp < 4; ++comp) {
        PrintFieldSummary(macro, lev, comp, comp);
      }
      for (int comp = 0; comp < f.nComp(); ++comp) {
        PrintFieldSummary(f, lev, comp, 6 + comp);
      }
    }
#ifdef LBM_TGV_METRICS
    PrintTgvMetrics(solver);
#endif
  }
  amrex::Finalize();
}
