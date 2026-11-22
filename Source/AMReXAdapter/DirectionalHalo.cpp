#include "DirectionalHalo.H"

#include <AMReX_Gpu.H>
#include <AMReX_ParallelContext.H>
#include <AMReX_ParallelDescriptor.H>
#include <AMReX_Print.H>

#include <algorithm>
#include <set>

using namespace amrex;

namespace lbm3d::detail {

void LaunchDirectionalHalo(Long total_cells, int ntags,
                           DirectionalHaloTag const* tags, Real* buffer,
                           int operation) {
  ParallelFor(total_cells, [=] AMREX_GPU_DEVICE(Long index) noexcept {
    int left = 0;
    int right = ntags;
    while (left + 1 < right) {
      int const middle = (left + right) / 2;
      if (tags[middle].cell_offset <= index) {
        left = middle;
      } else {
        right = middle;
      }
    }
    auto const& tag = tags[left];
    Long const cell = index - tag.cell_offset;
    int const i = tag.lo[0] + static_cast<int>(cell % tag.len[0]);
    int const j = tag.lo[1] +
                  static_cast<int>((cell / tag.len[0]) % tag.len[1]);
    int const k = tag.lo[2] +
                  static_cast<int>(cell / (tag.len[0] * tag.len[1]));
    for (int c = 0; c < tag.nq; ++c) {
      int const q = tag.q[c];
      Long const buffer_index = tag.offset + c * tag.npts + cell;
      if (operation == 0) {
        buffer[buffer_index] = tag.src(i + tag.shift[0], j + tag.shift[1],
                                        k + tag.shift[2], q);
      } else if (operation == 1) {
        tag.dst(i, j, k, q) = tag.src(i + tag.shift[0], j + tag.shift[1],
                                      k + tag.shift[2], q);
      } else {
        tag.dst(i, j, k, q) = buffer[buffer_index];
      }
    }
  });
}

} // namespace lbm3d::detail

bool DirectionalHalo::SupportsStencil(Vector<Real> const& dirx,
                                      Vector<Real> const& diry,
                                      Vector<Real> const& dirz) {
  if (dirx.size() != 19 || diry.size() != 19 || dirz.size() != 19) {
    return false;
  }
  std::set<std::array<int, 3>> directions;
  int counts[3] = {0, 0, 0};
  for (int q = 0; q < 19; ++q) {
    std::array<int, 3> direction{};
    for (int d = 0; d < 3; ++d) {
      Real const value = d == 0 ? dirx[q] : (d == 1 ? diry[q] : dirz[q]);
      if (value != Real(-1) && value != Real(0) && value != Real(1)) {
        return false;
      }
      direction[d] = static_cast<int>(value);
    }
    int const nonzero = (direction[0] != 0) + (direction[1] != 0) +
                        (direction[2] != 0);
    if (nonzero == 3) { return false; }
    ++counts[nonzero];
    directions.insert(direction);
  }
  return directions.size() == 19 && counts[0] == 1 && counts[1] == 6 &&
         counts[2] == 12;
}

DirectionalHalo::DirectionalHalo(MultiFab const& f, Geometry const& geom,
                                 Vector<Real> const& dirx,
                                 Vector<Real> const& diry,
                                 Vector<Real> const& dirz)
    : m_boxes(f.boxArray()), m_distribution(f.DistributionMap()) {
  AMREX_ALWAYS_ASSERT_WITH_MESSAGE(SupportsStencil(dirx, diry, dirz),
                                   "DirectionalHalo requires D3Q19.");
  AMREX_ALWAYS_ASSERT_WITH_MESSAGE(f.nComp() == 19,
                                   "DirectionalHalo requires 19 distribution components.");
  for (int q = 0; q < 19; ++q) {
    m_direction[q] = {static_cast<int>(dirx[q]), static_cast<int>(diry[q]),
                      static_cast<int>(dirz[q])};
  }

  auto const& fb = f.getFB(IntVect(1), geom.periodicity());
  m_serial_local = !fb.m_threadsafe_loc;
  m_serial_recv = !fb.m_threadsafe_rcv;
  Long generic_local_count = 0;
  Long generic_send_count = 0;
  Long generic_recv_count = 0;
  for (auto const& tag : *fb.m_LocTags) {
    // AMReX team members share local tags, but each rank writes its own FABs.
    if (m_distribution[tag.dstIndex] != ParallelDescriptor::MyProc()) {
      continue;
    }
    generic_local_count += tag.dbox.numPts() * f.nComp();
    AddTag(m_local, tag, m_boxes[tag.dstIndex], m_local_count);
  }
  for (auto const& [rank, tags] : *fb.m_SndTags) {
    Peer peer{rank, m_send_count, 0};
    for (auto const& tag : tags) {
      generic_send_count += tag.dbox.numPts() * f.nComp();
      AddTag(m_send, tag, m_boxes[tag.dstIndex], m_send_count);
    }
    peer.count = m_send_count - peer.offset;
    if (peer.count > 0) { m_send_peers.push_back(peer); }
  }
  for (auto const& [rank, tags] : *fb.m_RcvTags) {
    Peer peer{rank, m_recv_count, 0};
    for (auto const& tag : tags) {
      generic_recv_count += tag.dbox.numPts() * f.nComp();
      AddTag(m_recv, tag, m_boxes[tag.dstIndex], m_recv_count);
    }
    peer.count = m_recv_count - peer.offset;
    if (peer.count > 0) { m_recv_peers.push_back(peer); }
  }

  m_local_host_tags.resize(m_local.size());
  m_send_host_tags.resize(m_send.size());
  m_recv_host_tags.resize(m_recv.size());
  m_local_tags.resize(m_local.size());
  m_send_tags.resize(m_send.size());
  m_recv_tags.resize(m_recv.size());
  m_send_buffer.resize(m_send_count);
  m_recv_buffer.resize(m_recv_count);
#ifdef AMREX_USE_MPI
  if (!ParallelDescriptor::UseGpuAwareMpi()) {
    m_send_host_buffer.resize(m_send_count);
    m_recv_host_buffer.resize(m_recv_count);
  }
#endif
  Print() << "LBM_DIRECTIONAL_HALO active=1 rank0_local_values="
          << m_local_count << '/' << generic_local_count
          << " rank0_send_values=" << m_send_count << '/'
          << generic_send_count << " rank0_recv_values="
          << m_recv_count << '/' << generic_recv_count << '\n';
}

bool DirectionalHalo::matches(MultiFab const& f) const {
  return m_boxes == f.boxArray() && m_distribution == f.DistributionMap();
}

void DirectionalHalo::AddTag(std::vector<Segment>& segments,
                             FabArrayBase::CopyComTag const& tag,
                             Box const& dst_valid, Long& count) {
  for (int sx = -1; sx <= 1; ++sx) {
    for (int sy = -1; sy <= 1; ++sy) {
      for (int sz = -1; sz <= 1; ++sz) {
        if (sx == 0 && sy == 0 && sz == 0) { continue; }
        int const side[3] = {sx, sy, sz};
        Box bx = tag.dbox;
        for (int d = 0; d < 3; ++d) {
          if (side[d] < 0) {
            bx.setBig(d, std::min(bx.bigEnd(d), dst_valid.smallEnd(d) - 1));
          } else if (side[d] > 0) {
            bx.setSmall(d, std::max(bx.smallEnd(d), dst_valid.bigEnd(d) + 1));
          } else {
            bx.setSmall(d, std::max(bx.smallEnd(d), dst_valid.smallEnd(d)));
            bx.setBig(d, std::min(bx.bigEnd(d), dst_valid.bigEnd(d)));
          }
        }
        if (!bx.ok()) { continue; }

        Segment segment;
        segment.tag = tag;
        segment.box = bx;
        segment.offset = count;
        for (int q = 0; q < 19; ++q) {
          bool needed = true;
          for (int d = 0; d < 3; ++d) {
            if ((side[d] < 0 && m_direction[q][d] != 1) ||
                (side[d] > 0 && m_direction[q][d] != -1)) {
              needed = false;
            }
          }
          if (needed) { segment.q[segment.nq++] = q; }
        }
        if (segment.nq > 0) {
          count += bx.numPts() * segment.nq;
          segments.push_back(segment);
        }
      }
    }
  }
}

void DirectionalHalo::CopySegments(MultiFab& f,
                                    std::vector<Segment> const& segments,
                                    Gpu::HostVector<lbm3d::detail::DirectionalHaloTag>& host_tags,
                                    Gpu::DeviceVector<lbm3d::detail::DirectionalHaloTag>& device_tags,
                                    Real* buffer, int operation, bool serial) {
  if (segments.empty()) { return; }

  Long total_cells = 0;
  for (std::size_t t = 0; t < segments.size(); ++t) {
    auto const& segment = segments[t];
    auto& tag = host_tags[t];
    if (operation != 2) { tag.src = f.const_array(segment.tag.srcIndex); }
    if (operation != 0) { tag.dst = f.array(segment.tag.dstIndex); }
    tag.offset = segment.offset;
    tag.cell_offset = serial ? 0 : total_cells;
    tag.npts = segment.box.numPts();
    total_cells += tag.npts;
    tag.nq = segment.nq;
    for (int d = 0; d < 3; ++d) {
      tag.lo[d] = segment.box.smallEnd(d);
      tag.len[d] = segment.box.length(d);
      tag.shift[d] = segment.tag.sbox.smallEnd(d) -
                     segment.tag.dbox.smallEnd(d);
    }
    for (int q = 0; q < segment.nq; ++q) { tag.q[q] = segment.q[q]; }
  }
  Gpu::copyAsync(Gpu::hostToDevice, host_tags.begin(), host_tags.end(),
                 device_tags.begin());

  if (serial) {
    for (std::size_t t = 0; t < segments.size(); ++t) {
      lbm3d::detail::LaunchDirectionalHalo(
          segments[t].box.numPts(), 1, device_tags.data() + t, buffer,
          operation);
      Gpu::streamSynchronize();
    }
  } else {
    lbm3d::detail::LaunchDirectionalHalo(
        total_cells, static_cast<int>(segments.size()), device_tags.data(),
        buffer, operation);
  }
}

void DirectionalHalo::Fill(MultiFab& f) {
#ifdef BL_USE_TEAM
  if (ParallelDescriptor::TeamSize() > 1) {
    Gpu::streamSynchronize();
    ParallelDescriptor::MyTeam().MemoryBarrier();
  }
#endif
#ifdef AMREX_USE_MPI
  bool const device_mpi = ParallelDescriptor::UseGpuAwareMpi();
  int const tag = ParallelDescriptor::SeqNum();
  MPI_Comm const comm = ParallelContext::CommunicatorSub();
  std::vector<ParallelDescriptor::Message> receives;
  receives.reserve(m_recv_peers.size());
  for (auto const& peer : m_recv_peers) {
    int const rank = ParallelContext::global_to_local_rank(peer.rank);
    Real* const buffer = device_mpi ? m_recv_buffer.data()
                                    : m_recv_host_buffer.data();
    receives.push_back(ParallelDescriptor::Arecv(
        buffer + peer.offset, peer.count, rank, tag, comm));
  }
#endif

  CopySegments(f, m_send, m_send_host_tags, m_send_tags,
               m_send_buffer.data(), 0, false);
  // Send as soon as the packed device buffer is ready. Local ghost copies
  // can run while MPI transfers the remote halo.
  if (!m_send.empty()) {
    Gpu::streamSynchronize();
#ifdef AMREX_USE_MPI
    if (!device_mpi) {
      Gpu::copyAsync(Gpu::deviceToHost, m_send_buffer.begin(),
                     m_send_buffer.end(), m_send_host_buffer.begin());
      Gpu::streamSynchronize();
    }
#endif
  }

#ifdef AMREX_USE_MPI
  std::vector<ParallelDescriptor::Message> sends;
  sends.reserve(m_send_peers.size());
  for (auto const& peer : m_send_peers) {
    int const rank = ParallelContext::global_to_local_rank(peer.rank);
    Real* const buffer = device_mpi ? m_send_buffer.data()
                                    : m_send_host_buffer.data();
    sends.push_back(ParallelDescriptor::Asend(
        buffer + peer.offset, peer.count, rank, tag, comm));
  }
#endif

  CopySegments(f, m_local, m_local_host_tags, m_local_tags, nullptr, 1,
               m_serial_local);

#ifdef AMREX_USE_MPI
  for (auto& receive : receives) { receive.wait(); }
  for (auto& send : sends) { send.wait(); }
#endif

  // Finish local writes before unpacking remote data into ghost cells.
  Gpu::streamSynchronize();
#ifdef AMREX_USE_MPI
  if (!device_mpi && !m_recv.empty()) {
    Gpu::copyAsync(Gpu::hostToDevice, m_recv_host_buffer.begin(),
                   m_recv_host_buffer.end(), m_recv_buffer.begin());
  }
#endif
  CopySegments(f, m_recv, m_recv_host_tags, m_recv_tags,
               m_recv_buffer.data(), 2, m_serial_recv);
  Gpu::streamSynchronize();
#ifdef BL_USE_TEAM
  if (ParallelDescriptor::TeamSize() > 1) {
    ParallelDescriptor::MyTeam().MemoryBarrier();
  }
#endif
}
