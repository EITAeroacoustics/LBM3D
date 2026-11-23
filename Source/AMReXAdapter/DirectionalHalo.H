#ifndef LBM3D_DIRECTIONAL_HALO_H_
#define LBM3D_DIRECTIONAL_HALO_H_

#include <AMReX_Geometry.H>
#include <AMReX_GpuContainers.H>
#include <AMReX_MultiFab.H>

#include <array>
#include <functional>
#include <vector>

namespace lbm3d::detail {

struct DirectionalHaloTag {
  amrex::Array4<amrex::Real const> src;
  amrex::Array4<amrex::Real> dst;
  amrex::Long offset = 0;
  amrex::Long cell_offset = 0;
  amrex::Long npts = 0;
  int lo[3]{};
  int len[3]{};
  int shift[3]{};
  int q[19]{};
  int nq = 0;
};

} // namespace lbm3d::detail

// Exchange only the populations that pull streaming reads in a one-cell halo.
// The tag geometry and rank ownership come from AMReX FillBoundary metadata.
class DirectionalHalo {
public:
  [[nodiscard]] static bool SupportsStencil(
      amrex::Vector<amrex::Real> const& dirx,
      amrex::Vector<amrex::Real> const& diry,
      amrex::Vector<amrex::Real> const& dirz);

  DirectionalHalo(amrex::MultiFab const& f, amrex::Geometry const& geom,
                  amrex::Vector<amrex::Real> const& dirx,
                  amrex::Vector<amrex::Real> const& diry,
                  amrex::Vector<amrex::Real> const& dirz,
                  bool aa_pattern = false);

  [[nodiscard]] bool matches(amrex::MultiFab const& f,
                             bool aa_pattern = false) const;
  [[nodiscard]] bool hasMultipleIncomingPeers(bool reverse) const noexcept {
    return reverse ? m_send_peers.size() > 1 : m_recv_peers.size() > 1;
  }
  void Fill(amrex::MultiFab& f,
            std::function<void()> const& before_wait = {});
  void ScatterAA(amrex::MultiFab& f,
                 std::function<void()> const& before_wait = {});

private:
  struct Segment {
    amrex::FabArrayBase::CopyComTag tag;
    amrex::Box box;
    std::array<int, 19> q{};
    int nq = 0;
    amrex::Long offset = 0;
  };

  struct Peer {
    int rank = -1;
    amrex::Long offset = 0;
    amrex::Long count = 0;
  };

  static void CopySegments(amrex::MultiFab& f,
                           std::vector<Segment> const& segments,
                           amrex::Gpu::HostVector<lbm3d::detail::DirectionalHaloTag>& host_tags,
                           amrex::Gpu::DeviceVector<lbm3d::detail::DirectionalHaloTag>& device_tags,
                           amrex::Real* buffer, int operation, bool serial);

  void AddTag(std::vector<Segment>& segments,
              amrex::FabArrayBase::CopyComTag const& tag,
              amrex::Box const& dst_valid, amrex::Long& count);

  amrex::BoxArray m_boxes;
  amrex::DistributionMapping m_distribution;
  bool m_serial_local = false;
  bool m_serial_recv = false;
  bool m_aa_pattern = false;
  bool m_reverse_local_separate = false;
  std::array<std::array<int, 3>, 19> m_direction{};
  std::vector<Segment> m_local;
  std::vector<Segment> m_reverse_local;
  std::vector<Segment> m_send;
  std::vector<Segment> m_recv;
  std::vector<Peer> m_send_peers;
  std::vector<Peer> m_recv_peers;
  amrex::Long m_local_count = 0;
  amrex::Long m_reverse_local_count = 0;
  amrex::Long m_send_count = 0;
  amrex::Long m_recv_count = 0;
  amrex::Gpu::HostVector<lbm3d::detail::DirectionalHaloTag> m_local_host_tags;
  amrex::Gpu::HostVector<lbm3d::detail::DirectionalHaloTag> m_reverse_local_host_tags;
  amrex::Gpu::HostVector<lbm3d::detail::DirectionalHaloTag> m_send_host_tags;
  amrex::Gpu::HostVector<lbm3d::detail::DirectionalHaloTag> m_recv_host_tags;
  amrex::Gpu::DeviceVector<lbm3d::detail::DirectionalHaloTag> m_local_tags;
  amrex::Gpu::DeviceVector<lbm3d::detail::DirectionalHaloTag> m_reverse_local_tags;
  amrex::Gpu::DeviceVector<lbm3d::detail::DirectionalHaloTag> m_send_tags;
  amrex::Gpu::DeviceVector<lbm3d::detail::DirectionalHaloTag> m_recv_tags;
  amrex::Gpu::DeviceVector<amrex::Real> m_send_buffer;
  amrex::Gpu::DeviceVector<amrex::Real> m_recv_buffer;
  amrex::Gpu::PinnedVector<amrex::Real> m_send_host_buffer;
  amrex::Gpu::PinnedVector<amrex::Real> m_recv_host_buffer;
};

#endif
