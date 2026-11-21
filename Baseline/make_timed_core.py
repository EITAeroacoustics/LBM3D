"""Make a build-local timing copy of the unmodified iLBMReX core."""

import sys
from pathlib import Path


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"expected one timing anchor, found {source.count(old)}: {old!r}")
    return source.replace(old, new)


def main() -> None:
    source_path, output_path = map(Path, sys.argv[1:])
    source = source_path.read_text()
    source = replace_once(source, "#include <AMReX_ParallelDescriptor.H>",
                          "#include <AMReX_ParallelDescriptor.H>\n"
                          "#include <AMReX_GpuDevice.H>")
    source = replace_once(source,
                          "  int last_plot_file_step = 0;\n\n  for (int step =",
                          "  int last_plot_file_step = 0;\n"
                          "  double measured_start = 0.0;\n\n  for (int step =")
    source = replace_once(source,
                          "    amrex::Print() << \"\\nCoarse STEP \" << step + 1",
                          "    if (step == 100) {\n"
                          "      amrex::Gpu::streamSynchronizeAll();\n"
                          "      amrex::ParallelDescriptor::Barrier();\n"
                          "      measured_start = amrex::second();\n"
                          "    }\n"
                          "    amrex::Print() << \"\\nCoarse STEP \" << step + 1")
    source = replace_once(source,
                          "    if (cur_time >= stop_time - 1.e-6 * dt[0])\n",
                          "    if (step == 599) {\n"
                          "      amrex::Gpu::streamSynchronizeAll();\n"
                          "      double elapsed = amrex::second() - measured_start;\n"
                          "      amrex::ParallelDescriptor::ReduceRealMax(elapsed);\n"
                          "      amrex::Print() << \"LBM_BASELINE_TIMING steps=500 elapsed_max_s=\"\n"
                          "                     << elapsed << \" sec_per_step=\"\n"
                          "                     << elapsed / 500.0 << '\\n';\n"
                          "    }\n"
                          "    if (cur_time >= stop_time - 1.e-6 * dt[0])\n")
    output_path.write_text(source)


if __name__ == "__main__":
    main()
