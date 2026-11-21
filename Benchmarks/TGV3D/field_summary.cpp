#include <iomanip>

#include <AMReX.H>
#include <AMReX_MultiFab.H>
#include <AMReX_Print.H>

#include <AmrCoreLBM.H>
#include <ProblemInit.H>

void InitializeProblem(amrex::MultiFab& macro, amrex::Geometry const& geom,
                       amrex::Real nu);

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
        amrex::Print() << std::setprecision(17)
                       << "FIELD_SUMMARY lev=" << lev << " comp=" << comp
                       << " sum=" << sum << " norm2=" << norm2
                       << " min=" << min << " max=" << max << '\n';
      }
    }
  }
  amrex::Finalize();
}
