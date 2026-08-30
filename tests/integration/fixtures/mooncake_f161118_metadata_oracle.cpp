// Metadata-only oracle for the pinned vanilla Mooncake f161118 commit.
//
// This executable deliberately does not initialize TransferEngine, discover
// devices, open sockets, move payload bytes, or call CUDA.  It links the
// already-built pinned Store/TE libraries and exercises only in-memory state
// machines also covered by the upstream unit tests.

#include <glog/logging.h>

#include <cstdint>
#include <iostream>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "allocation_strategy.h"
#include "config.h"
#include "eviction_strategy.h"
#include "master_service.h"
#include "multi_transport.h"
#include "replica.h"
#include "types.h"

namespace {

using mooncake::AllocatorManager;
using mooncake::ErrorCode;
using mooncake::FIFOEvictionStrategy;
using mooncake::LRUEvictionStrategy;
using mooncake::MasterService;
using mooncake::MultiTransport;
using mooncake::OffsetBufferAllocator;
using mooncake::RandomAllocationStrategy;
using mooncake::ReplicateConfig;
using mooncake::ReplicaStatus;
using mooncake::ReplicaType;
using mooncake::Status;
using mooncake::TenantId;
using mooncake::Transport;
using mooncake::UUID;

constexpr std::uintptr_t kBase0 = 0x100000000ULL;
constexpr std::uintptr_t kBase1 = 0x200000000ULL;
constexpr std::size_t kCapacity = 16 * 1024 * 1024;

[[noreturn]] void fail(const std::string& message) {
    throw std::runtime_error(message);
}

void require(bool condition, const std::string& message) {
    if (!condition) fail(message);
}

std::string quoted(const std::string& value) {
    std::ostringstream stream;
    stream << '"';
    for (const char character : value) {
        switch (character) {
            case '\\':
                stream << "\\\\";
                break;
            case '"':
                stream << "\\\"";
                break;
            case '\n':
                stream << "\\n";
                break;
            default:
                stream << character;
        }
    }
    stream << '"';
    return stream.str();
}

std::string error_name(ErrorCode error) { return mooncake::toString(error); }

std::string replica_status_name(ReplicaStatus status) {
    std::ostringstream stream;
    stream << status;
    return stream.str();
}

std::shared_ptr<OffsetBufferAllocator> make_allocator(
    const std::string& name, std::uintptr_t base,
    std::size_t capacity = kCapacity) {
    return std::make_shared<OffsetBufferAllocator>(name, base, capacity, name);
}

std::string allocator_observation() {
    RandomAllocationStrategy strategy;
    AllocatorManager empty_manager;
    auto empty = strategy.Allocate(empty_manager, 1024, 1, {}, {});
    require(!empty.has_value(), "empty allocator unexpectedly succeeded");

    AllocatorManager preferred_manager;
    auto ordinary = make_allocator("ordinary", kBase0);
    auto preferred = make_allocator("preferred", kBase1);
    preferred_manager.addAllocator("ordinary", ordinary);
    preferred_manager.addAllocator("preferred", preferred);
    auto preferred_result =
        strategy.Allocate(preferred_manager, 1024, 1, {"preferred"}, {});
    require(preferred_result.has_value(), "preferred allocation failed");
    require(preferred_result->size() == 1, "preferred allocation count drift");
    const auto preferred_descriptor =
        preferred_result->at(0).get_descriptor().get_memory_descriptor();

    AllocatorManager best_effort_manager;
    auto first = make_allocator("segment-a", kBase0);
    auto second = make_allocator("segment-b", kBase1);
    best_effort_manager.addAllocator("segment-a", first);
    best_effort_manager.addAllocator("segment-b", second);
    auto best_effort =
        strategy.Allocate(best_effort_manager, 1024, 3, {}, {});
    require(best_effort.has_value(), "best-effort allocation failed");
    std::set<std::string> distinct_segments;
    for (const auto& replica : best_effort.value()) {
        for (const auto& name : replica.get_segment_names()) {
            if (name) distinct_segments.insert(*name);
        }
    }

    auto extent_allocator = make_allocator("extent", kBase0, 4096);
    auto extent_a = extent_allocator->allocate(100);
    auto extent_b = extent_allocator->allocate(200);
    require(extent_a && extent_b, "initial extent allocation failed");
    const auto offset_a = reinterpret_cast<std::uintptr_t>(extent_a->data()) - kBase0;
    const auto offset_b = reinterpret_cast<std::uintptr_t>(extent_b->data()) - kBase0;
    extent_a.reset();
    auto extent_c = extent_allocator->allocate(50);
    require(static_cast<bool>(extent_c), "extent reuse allocation failed");
    const auto offset_c = reinterpret_cast<std::uintptr_t>(extent_c->data()) - kBase0;

    std::ostringstream stream;
    stream << "{\"empty_error\":" << quoted(error_name(empty.error()))
           << ",\"preferred_endpoint\":"
           << quoted(preferred_descriptor.buffer_descriptor.transport_endpoint_)
           << ",\"preferred_size_bytes\":"
           << preferred_descriptor.buffer_descriptor.size_
           << ",\"best_effort_replica_count\":" << best_effort->size()
           << ",\"best_effort_distinct_segments\":"
           << distinct_segments.size() << ",\"offset_extent_trace\":["
           << offset_a << ',' << offset_b << ',' << offset_c << "]}";
    return stream.str();
}

std::string eviction_observation() {
    LRUEvictionStrategy lru;
    lru.AddKey("key1");
    lru.AddKey("key2");
    const auto lru_first = lru.EvictKey();
    lru.AddKey("key3");
    lru.AddKey("key4");
    lru.UpdateKey("key2");
    lru.UpdateKey("key3");
    const auto lru_second = lru.EvictKey();

    FIFOEvictionStrategy fifo;
    fifo.AddKey("key1");
    fifo.AddKey("key2");
    fifo.RemoveKey("key2");
    const auto fifo_size_after_remove = fifo.GetSize();
    const auto fifo_first = fifo.EvictKey();
    fifo.AddKey("key3");
    fifo.AddKey("key4");
    fifo.UpdateKey("key2");
    fifo.UpdateKey("key3");
    const auto fifo_second = fifo.EvictKey();

    std::ostringstream stream;
    stream << "{\"lru_evicted\":[" << quoted(lru_first) << ','
           << quoted(lru_second) << "],\"fifo_evicted\":["
           << quoted(fifo_first) << ',' << quoted(fifo_second)
           << "],\"fifo_size_after_remove\":" << fifo_size_after_remove << '}';
    return stream.str();
}

std::string master_observation() {
    MasterService service;
    const UUID client_id = mooncake::generate_uuid();
    mooncake::Segment segment;
    segment.id = mooncake::generate_uuid();
    segment.name = "metadata-segment";
    segment.base = 0x300000000ULL;
    segment.size = kCapacity;
    segment.te_endpoint = "metadata-segment";
    require(service.MountSegment(segment, client_id).has_value(),
            "master segment mount failed");

    const std::string key = "metadata-key";
    const auto missing = service.GetReplicaListForAdmin(key, TenantId::Default());
    require(!missing.has_value(), "missing key unexpectedly visible");

    ReplicateConfig config;
    config.replica_num = 1;
    const auto put_start =
        service.PutStart(client_id, key, TenantId::Default(), 1024, config);
    require(put_start.has_value(), "PutStart failed");
    require(put_start->size() == 1, "PutStart replica count drift");
    const auto pending_status = put_start->front().status;
    const auto pending = service.GetReplicaListForAdmin(key, TenantId::Default());
    require(!pending.has_value(), "pending key unexpectedly readable");

    const auto put_end =
        service.PutEnd(client_id, key, TenantId::Default(), ReplicaType::MEMORY);
    require(put_end.has_value(), "PutEnd failed");
    const auto committed = service.GetReplicaListForAdmin(key, TenantId::Default());
    require(committed.has_value(), "committed key not readable");
    require(committed->replicas.size() == 1, "committed replica count drift");
    const auto committed_status = committed->replicas.front().status;

    const auto remove = service.Remove(key, TenantId::Default());
    require(remove.has_value(), "Remove failed");
    const auto removed = service.GetReplicaListForAdmin(key, TenantId::Default());
    require(!removed.has_value(), "removed key unexpectedly visible");

    std::ostringstream stream;
    stream << "{\"missing_get\":" << quoted(error_name(missing.error()))
           << ",\"put_start_status\":"
           << quoted(replica_status_name(pending_status))
           << ",\"pending_get\":" << quoted(error_name(pending.error()))
           << ",\"put_end\":\"OK\",\"committed_get\":\"OK\""
           << ",\"committed_replica_count\":" << committed->replicas.size()
           << ",\"committed_status\":"
           << quoted(replica_status_name(committed_status))
           << ",\"remove\":\"OK\",\"removed_get\":"
           << quoted(error_name(removed.error())) << '}';
    return stream.str();
}

std::string transfer_engine_observation() {
    const auto slice_size = mooncake::globalConfig().slice_size;

    std::string local_name = "metadata-only";
    MultiTransport transport(nullptr, local_name);
    auto overflow_batch = transport.allocateBatchID(1);
    std::vector<MultiTransport::TransferRequest> overflow_requests(2);
    const Status overflow =
        transport.submitTransfer(overflow_batch, overflow_requests);
    const Status overflow_free = transport.freeBatchID(overflow_batch);

    auto busy_batch = transport.allocateBatchID(1);
    auto& busy_desc = Transport::toBatchDesc(busy_batch);
    busy_desc.task_list.resize(1);
    busy_desc.task_list.front().is_finished = false;
    const Status busy_free = transport.freeBatchID(busy_batch);
    busy_desc.task_list.front().is_finished = true;
    const Status completed_free = transport.freeBatchID(busy_batch);

    Transport::TransferTask task;
    Transport::Slice first{};
    first.length = slice_size;
    first.status = Transport::Slice::PENDING;
    first.task = &task;
    first.markSuccess();
    Transport::Slice second{};
    second.length = slice_size;
    second.status = Transport::Slice::PENDING;
    second.task = &task;
    second.markSuccess();
    Transport::Slice tail{};
    tail.length = 1;
    tail.status = Transport::Slice::PENDING;
    tail.task = &task;
    tail.markSuccess();

    std::ostringstream stream;
    stream << "{\"default_slice_size_bytes\":" << slice_size
           << ",\"overflow_submit\":" << quoted(overflow.ToString())
           << ",\"overflow_batch_free\":" << quoted(overflow_free.ToString())
           << ",\"unfinished_batch_free\":" << quoted(busy_free.ToString())
           << ",\"finished_batch_free\":" << quoted(completed_free.ToString())
           << ",\"successful_slice_count\":" << task.success_slice_count
           << ",\"transferred_bytes\":" << task.transferred_bytes << '}';
    return stream.str();
}

}  // namespace

int main(int argc, char** argv) {
    google::InitGoogleLogging(argv[0]);
    FLAGS_logtostderr = true;
    try {
        std::cout
            << "{\"schema\":\"moonkvsim.external-mooncake-metadata-oracle.v1\""
            << ",\"execution_boundary\":{\"cuda\":false,\"gpu\":false,"
               "\"network\":false,\"payload_copy\":false}"
            << ",\"allocator\":" << allocator_observation()
            << ",\"eviction\":" << eviction_observation()
            << ",\"master\":" << master_observation()
            << ",\"transfer_engine\":" << transfer_engine_observation()
            << "}\n";
    } catch (const std::exception& error) {
        std::cerr << "metadata oracle failed: " << error.what() << '\n';
        google::ShutdownGoogleLogging();
        return 2;
    }
    google::ShutdownGoogleLogging();
    return 0;
}
