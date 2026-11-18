// Compile this harness with the referenced, unmodified Mooncake controller.
// No Store RPC, CUDA, third-party JSON parser or mock policy is involved.
#include "aegiskv_controller.h"
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
using namespace mooncake::aegiskv;

int main() {
  double full, slack, elapsed, hbm_time, dram_time;
  std::cout << std::setprecision(17);
  while (std::cin >> full >> slack >> elapsed >> hbm_time >> dram_time) {
    AegisController c;
    std::string error;
    auto check = [&](bool ok) { if (!ok) throw std::runtime_error(error); };
    check(c.RegisterDramPool({"dram", 1000, "host-dram"}, &error));
    check(c.RegisterHbmTarget({"hbm", "worker-1", "gpu-1", 1000,
                              .2, 0, .5, .5, .05, 4}, &error));
    check(c.RegisterRequest({"r", "revision", "abi", "tp1", "gpu-0",
                             "hbm", 1, full}, &error));
    check(c.UpdateSlack({"r", slack, 1000, 1, true, false}, &error));
    const double now = 1000 + elapsed;
    auto candidate = [&](std::string id, ProtectionTier tier, double recovery) {
      ChunkCandidate x;
      x.chunk_id = id; x.request_id = "r";
      x.pool_id = tier == ProtectionTier::DRAM ? "dram" : "hbm";
      x.storage_key = "same-key"; x.storage_keys = {"same-key"};
      x.tier = tier; x.ordinal = 0; x.bytes = 100; x.shard_count = 2;
      x.tier_recovery_ms = recovery; x.route_version = 1;
      x.model_revision = "revision"; x.kv_abi = "abi"; x.layout_id = "tp1";
      return x;
    };
    auto h = candidate("h", ProtectionTier::PEER_HBM, hbm_time);
    auto d = candidate("d", ProtectionTier::DRAM, dram_time);
    auto ha = c.Admit(h, now);
    double pending_harm = c.CurrentRecoveryHarmMs("r", now);
    if (ha.decision == AdmissionDecision::ADMIT_HBM)
      check(c.CompleteCopy({"h",2,1,"revision","abi","tp1",true}, now, &error));
    auto da = c.Admit(d, now);
    if (da.decision == AdmissionDecision::ADMIT_DRAM)
      check(c.CompleteCopy({"d",2,1,"revision","abi","tp1",true}, now, &error));
    std::cout << "{\"h_gain\":" << ha.gain_ms
      << ",\"d_gain\":" << da.gain_ms
      << ",\"pending_harm\":" << pending_harm
      << ",\"harm\":" << c.CurrentRecoveryHarmMs("r",now)
      << ",\"h_decision\":" << int(ha.decision)
      << ",\"d_decision\":" << int(da.decision)
      << ",\"quotas\":[";
    for (int i=0; i<6; ++i) {
      auto pubs = c.ControlWindow({{"hbm",i==4}}, now+i+1);
      if (i) std::cout << ',';
      std::cout << pubs.at(0).quota_bytes;
    }
    std::cout << "]}" << std::endl;
  }
}
