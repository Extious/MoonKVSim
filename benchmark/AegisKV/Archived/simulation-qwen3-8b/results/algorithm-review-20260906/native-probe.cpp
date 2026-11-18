// Bounded review probe; compiles the unchanged native Mooncake controller.
#include "aegiskv_controller.h"
#include <iostream>
#include <stdexcept>
using namespace mooncake::aegiskv;
void setup(AegisController& c) {
  std::string e;
  if (!c.RegisterHbmTarget({"h","worker1","gpu1",1000,.5,0,.5,.5,.05,4},&e) ||
      !c.RegisterDramPool({"d",1000,"store"},&e) ||
      !c.RegisterRequest({"r","rev","abi","layout","gpu0","h",1,100},&e) ||
      !c.UpdateSlack({"r",0,0,1,true,false},&e)) throw std::runtime_error(e);
}
ChunkCandidate chunk(const char* id, unsigned ordinal, unsigned bytes, double recovery, ProtectionTier tier) {
  ChunkCandidate x;
  x.chunk_id=id;x.request_id="r";x.pool_id=tier==ProtectionTier::DRAM?"d":"h";
  x.storage_key=id;x.storage_keys={id};x.tier=tier;x.ordinal=ordinal;x.bytes=bytes;
  x.shard_count=1;x.tier_recovery_ms=recovery;x.route_version=1;
  x.model_revision="rev";x.kv_abi="abi";x.layout_id="layout";return x;
}
int main() {
  std::cout<<"{\n";
  {AegisController c;setup(c);
   auto a=c.Admit(chunk("first",0,100,100,ProtectionTier::DRAM),1);
   auto b=c.Admit(chunk("second",1,100,80,ProtectionTier::DRAM),1);
   auto g=c.Admit(chunk("group",0,200,80,ProtectionTier::DRAM),1);
   std::cout<<"\"prefix\":{\"first_decision\":"<<int(a.decision)<<",\"first_gain\":"<<a.gain_ms<<",\"second_decision\":"<<int(b.decision)<<",\"second_reason\":\""<<b.reason<<"\",\"group_decision\":"<<int(g.decision)<<",\"group_gain\":"<<g.gain_ms<<"},\n";
  }
  {AegisController c;setup(c);auto a=c.ControlWindow({{"h",true}},1000);auto b=c.ControlWindow({{"h",true}},1000);
   std::cout<<"\"duplicate_pressure\":{\"first_quota\":"<<a[0].quota_bytes<<",\"same_timestamp_retry_quota\":"<<b[0].quota_bytes<<"},\n";
  }
  {AegisController c;setup(c);auto a=c.Admit(chunk("victim",0,400,20,ProtectionTier::PEER_HBM),1);std::string e;
   if(a.decision!=AdmissionDecision::ADMIT_HBM || !c.CompleteCopy({"victim",1,1,"rev","abi","layout",true},2,&e))throw std::runtime_error(e);
   auto shrink=c.ControlWindow({{"h",true}},1000);
   // Model a dropped publication or failed physical delete by not enacting it.
   auto next=c.ControlWindow({{"h",false}},2000);
   std::cout<<"\"unacked_reclaim\":{\"first_victim_count\":"<<shrink[0].reclaimed_chunk_ids.size()<<",\"native_accounted_bytes\":"<<shrink[0].allocated_bytes<<",\"next_victim_count\":"<<next[0].reclaimed_chunk_ids.size()<<",\"next_quota_satisfied\":"<<(next[0].quota_satisfied?"true":"false")<<"}\n";
  }
  std::cout<<"}\n";
}
