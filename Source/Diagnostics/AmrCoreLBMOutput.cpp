#include <AmrCoreLBM.H>

#include <AMReX_GpuLaunch.H>
#include <AMReX_ParallelDescriptor.H>
#include <AMReX_PlotFileUtil.H>
#include <AMReX_VisMF.H>

#include <fstream>
#include <iomanip>

using namespace amrex;

// get plotfile name
std::string AmrCoreLBM::PlotFileName(int lev) const {
  return amrex::Concatenate(plot_file, lev, 5);
}

amrex::Vector<std::unique_ptr<amrex::MultiFab>> AmrCoreLBM::PlotFileMF() const {
  amrex::Vector<std::unique_ptr<amrex::MultiFab>> plot_mfs;

  // Component indices in macro_new
  constexpr int rho_comp = 0;
  constexpr int ux_comp = 1;
  constexpr int uy_comp = 2;
  constexpr int uz_comp = 3;
  constexpr int vor_comp = 4;
  constexpr int P_comp = 5;

  const int n_macro_out = 6; // rho, ux, uy, uz, vor, Pressure
  const int f_first_comp = n_macro_out;

  const bool marker_levelset_ibm =
      (m_ib_method != IBMMethodMarker ||
       m_marker_par.geometry_type == MarkerIBParams::GeometryCylinder);
  const bool want_phi = (m_use_cylinder && m_ls && marker_levelset_ibm);

  for (int lev = 0; lev <= finest_level; ++lev) {
    amrex::Print() << "Preparing plotfile data at level " << lev << "\n";

    AMREX_ALWAYS_ASSERT(macro_new[lev].nComp() > P_comp);
    AMREX_ALWAYS_ASSERT(f_new[lev].nComp() >= ndir);

    // Do we have phi on this level?
    bool have_phi_on_lev = (want_phi && m_ls->has_level(lev));

    int n_phi = have_phi_on_lev ? 1 : 0;
    int ncomp_out = n_macro_out + ndir + n_phi;

    // Allocate output MultiFab with desired layout
    plot_mfs.push_back(
        std::make_unique<amrex::MultiFab>(grids[lev], dmap[lev], ncomp_out, 0));
    amrex::MultiFab &out = *plot_mfs.back();

    // ---- Copy macroscopic fields ----
    amrex::MultiFab::Copy(out, macro_new[lev], rho_comp, rho_comp, 1, 0);
    amrex::MultiFab::Copy(out, macro_new[lev], ux_comp, ux_comp, 1, 0);
    amrex::MultiFab::Copy(out, macro_new[lev], uy_comp, uy_comp, 1, 0);
    amrex::MultiFab::Copy(out, macro_new[lev], uz_comp, uz_comp, 1, 0);
    amrex::MultiFab::Copy(out, macro_new[lev], vor_comp, vor_comp, 1, 0);
    amrex::MultiFab::Copy(out, macro_new[lev], P_comp, P_comp, 1, 0);

    // ---- Copy all ndir distribution functions ----
    for (int i = 0; i < ndir; ++i) {
      amrex::MultiFab::Copy(out, f_new[lev], i, f_first_comp + i, 1, 0);
    }

    // ---- Copy level-set phi, if present, using ParallelCopy ----
    if (have_phi_on_lev) {
      const amrex::MultiFab &phi_src = m_ls->phi_at(lev);
      const int phi_dest_comp = out.nComp() - 1;

      // Scratch MF with the *same* BA & DM as out
      amrex::MultiFab phi_cc(out.boxArray(), out.DistributionMap(), 1, 0);
      phi_cc.setVal(0.0);

      // This handles different BoxArray / DistributionMapping internally
      phi_cc.ParallelCopy(phi_src, 0, 0, 1, 0, 0, Geom(lev).periodicity());

      amrex::MultiFab::Copy(out, phi_cc, 0, phi_dest_comp, 1, 0);

      // Marker IBM uses fictitious fluid inside the body; mask solid-interior
      // macroscopic fields in plot output so visualization reflects the
      // physical exterior flow.
      if (m_ib_method == IBMMethodMarker &&
          m_marker_par.geometry_type == MarkerIBParams::GeometryCylinder) {
        const amrex::Real ubx = m_marker_par.ubx;
        const amrex::Real uby = m_marker_par.uby;
        const amrex::Real ubz = m_marker_par.ubz;
        for (amrex::MFIter mfi(out, amrex::TilingIfNotGPU()); mfi.isValid();
             ++mfi) {
          const amrex::Box &bx = mfi.validbox();
          auto out_a = out[mfi].array();
          auto phi_a = phi_cc[mfi].const_array();
          amrex::ParallelFor(
              bx, [=] AMREX_GPU_DEVICE(int i, int j, int k) noexcept {
                if (phi_a(i, j, k, 0) < amrex::Real(0.0)) {
                  out_a(i, j, k, ux_comp) = ubx;
                  out_a(i, j, k, uy_comp) = uby;
                  out_a(i, j, k, uz_comp) = ubz;
                  out_a(i, j, k, vor_comp) = amrex::Real(0.0);
                }
              });
        }
      }
    }

    amrex::Print() << "m_use_cylinder = " << m_use_cylinder
                   << ", m_ls = " << (m_ls ? "not null" : "null")
                   << ", phi_written = " << (have_phi_on_lev ? "yes" : "no")
                   << std::endl;
  }

  return plot_mfs;
}

// set plotfile variable names
Vector<std::string> AmrCoreLBM::PlotFileVarNames() const {
  Vector<std::string> names;

  // Use level 0 as reference (all levels have the same nComp layout)
  const int nmacro = macro_new[0].nComp();
  const int nmeso = f_new[0].nComp();
  const bool marker_levelset_ibm =
      (m_ib_method != IBMMethodMarker ||
       m_marker_par.geometry_type == MarkerIBParams::GeometryCylinder);
  const bool have_phi =
      (m_use_cylinder && m_ls && m_ls->has_level(0) && marker_levelset_ibm);
  const int nphi = have_phi ? 1 : 0;

  // --- Macroscopic variables ---
  if (nmacro > 0)
    names.push_back("rho");
  if (nmacro > 1)
    names.push_back("ux");
  if (nmacro > 2)
    names.push_back("uy");
  if (nmacro > 3)
    names.push_back("uz");
  if (nmacro > 4)
    names.push_back("vor");
  if (nmacro > 5)
    names.push_back("Pressure");

  // Any extra macro components beyond the first 6 get generic names
  for (int m = 6; m < nmacro; ++m) {
    names.push_back("macro_" + std::to_string(m));
  }

  // --- Mesoscopic distribution functions f_i ---
  for (int i = 0; i < nmeso; ++i) {
    names.push_back("f_new_" + std::to_string(i));
  }

  // --- Level-set field φ, if present ---
  if (have_phi) {
    names.push_back("phi");
  }

  const int expected = nmacro + nmeso + nphi;
  if (static_cast<int>(names.size()) != expected) {
    amrex::Print() << "WARNING: PlotFileVarNames: names.size() = "
                   << names.size() << " but expected " << expected << "\n";
  } else {
    amrex::Print() << "PlotFileVarNames: total vars = " << names.size() << "\n";
  }

  return names;
}

// write plotfile to disk
void AmrCoreLBM::WritePlotFile() const {

  // Create MultiFabs for output
  amrex::Vector<std::unique_ptr<amrex::MultiFab>> mf_ptrs = PlotFileMF();

  // Convert unique_ptr to raw pointers for AMReX
  amrex::Vector<const amrex::MultiFab *> mf;
  for (const auto &uptr : mf_ptrs) {
    mf.push_back(uptr.get()); // Extract raw pointer
  }
  const std::string &plotfilename = PlotFileName(istep[0]);
  Vector<std::string> varnames = PlotFileVarNames();

  // Write plot file
  amrex::WriteMultiLevelPlotfile(plotfilename, finest_level + 1, mf, varnames,
                                 Geom(), t_new[0], istep, refRatio());
}

void AmrCoreLBM::WriteCheckpointFile() const {
  /*
      // chk00010            write a checkpoint file with this root directory
      // chk00010/Header     this contains information you need to save (e.g.,
     finest_level, t_new, etc.) and also
      //                     the BoxArrays at each level
      // chk00010/Level_0/
      // chk00010/Level_1/
      // etc.                these subdirectories will hold the MultiFab data at
     each level of refinement

      // checkpoint file name, e.g., chk00010
      const std::string& checkpointname = amrex::Concatenate(chk_file,istep[0]);

      amrex::Print() << "Writing checkpoint " << checkpointname << "\n";

      const int nlevels = finest_level+1;

      // ---- prebuild a hierarchy of directories
      // ---- dirName is built first.  if dirName exists, it is renamed.  then
     build
      // ---- dirName/subDirPrefix_0 .. dirName/subDirPrefix_nlevels-1
      // ---- if callBarrier is true, call ParallelDescriptor::Barrier()
      // ---- after all directories are built
      // ---- ParallelDescriptor::IOProcessor() creates the directories
      amrex::PreBuildDirectorHierarchy(checkpointname, "Level_", nlevels, true);

      // write Header file
     if (ParallelDescriptor::IOProcessor()) {

         std::string HeaderFileName(checkpointname + "/Header");
         VisMF::IO_Buffer io_buffer(VisMF::IO_Buffer_Size);
         std::ofstream HeaderFile;
         HeaderFile.rdbuf()->pubsetbuf(io_buffer.dataPtr(), io_buffer.size());
         HeaderFile.open(HeaderFileName.c_str(), std::ofstream::out   |
                                                 std::ofstream::trunc |
                                                 std::ofstream::binary);
         if( ! HeaderFile.good()) {
             amrex::FileOpenFailed(HeaderFileName);
         }

         HeaderFile.precision(17);

         // write out title line
         HeaderFile << "Checkpoint file for AmrCoreLBM\n";

         // write out finest_level
         HeaderFile << finest_level << "\n";

         // write out array of istep
         for (int i = 0; i < istep.size(); ++i) {
             HeaderFile << istep[i] << " ";
         }
         HeaderFile << "\n";

         // write out array of dt
         for (int i = 0; i < dt.size(); ++i) {
             HeaderFile << dt[i] << " ";
         }
         HeaderFile << "\n";

         // write out array of t_new
         for (int i = 0; i < t_new.size(); ++i) {
             HeaderFile << t_new[i] << " ";
         }
         HeaderFile << "\n";

         // write the BoxArray at each level
         for (int lev = 0; lev <= finest_level; ++lev) {
             boxArray(lev).writeOn(HeaderFile);
             HeaderFile << '\n';
         }
     }

     // write the MultiFab data to, e.g., chk00010/Level_0/
     for (int lev = 0; lev <= finest_level; ++lev) {
         VisMF::Write(macro_new[lev],amrex::MultiFabFileFullPrefix(lev,
     checkpointname, "Level_", "phi"));
     }
  */
}

void AmrCoreLBM::ReadCheckpointFile() {
  /*
      amrex::Print() << "Restart from checkpoint " << restart_chkfile << "\n";

      // Header
      std::string File(restart_chkfile + "/Header");

      VisMF::IO_Buffer io_buffer(VisMF::GetIOBufferSize());

      Vector<char> fileCharPtr;
      ParallelDescriptor::ReadAndBcastFile(File, fileCharPtr);
      std::string fileCharPtrString(fileCharPtr.dataPtr());
      std::istringstream is(fileCharPtrString, std::istringstream::in);

      std::string line, word;

      // read in title line
      std::getline(is, line);

      // read in finest_level
      is >> finest_level;
      GotoNextLine(is);

      // read in array of istep
      std::getline(is, line);
      {
          std::istringstream lis(line);
          int i = 0;
          while (lis >> word) {
              istep[i++] = std::stoi(word);
          }
      }

      // read in array of dt
      std::getline(is, line);
      {
          std::istringstream lis(line);
          int i = 0;
          while (lis >> word) {
              dt[i++] = std::stod(word);
          }
      }

      // read in array of t_new
      std::getline(is, line);
      {
          std::istringstream lis(line);
          int i = 0;
          while (lis >> word) {
              t_new[i++] = std::stod(word);
          }
      }

      for (int lev = 0; lev <= finest_level; ++lev) {

          // read in level 'lev' BoxArray from Header
          BoxArray ba;
          ba.readFrom(is);
          GotoNextLine(is);

          // create a distribution mapping
          DistributionMapping dm { ba, ParallelDescriptor::NProcs() };

          // set BoxArray grids and DistributionMapping dmap in AMReX_AmrMesh.H
     class SetBoxArray(lev, ba); SetDistributionMap(lev, dm);

          // build MultiFab and FluxRegister data
          int ncomp = 1;
          int nghost = 0;
          phi_old[lev].define(grids[lev], dmap[lev], ncomp, nghost);
          phi_new[lev].define(grids[lev], dmap[lev], ncomp, nghost);

          if (lev > 0 && do_reflux) {
              flux_reg[lev].reset(new FluxRegister(grids[lev], dmap[lev],
     refRatio(lev-1), lev, ncomp));
          }

          // build face velocity MultiFabs
          for (int idim = 0; idim < AMREX_SPACEDIM; idim++)
          {
              facevel[lev][idim] =
     MultiFab(amrex::convert(ba,IntVect::TheDimensionVector(idim)), dm, 1, 1);
          }
      }

      // read in the MultiFab data
      for (int lev = 0; lev <= finest_level; ++lev) {
          VisMF::Read(phi_new[lev],
                      amrex::MultiFabFileFullPrefix(lev, restart_chkfile,
     "Level_", "phi"));
      }

  */
}
