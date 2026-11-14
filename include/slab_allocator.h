#ifndef FASTKV_SLAB_ALLOCATOR_H
#define FASTKV_SLAB_ALLOCATOR_H

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory_resource>
#include <mutex>
#include <vector>

// Thread-safe, fixed-size slab allocator used by Fast-KV's stored values.
// Large or over-aligned requests fall back to operator new/delete.
// Slabs stay available for reuse until the KVStore is destroyed.
class SlabResource final : public std::pmr::memory_resource {
public:
    struct Stats {
        std::size_t reservedBytes = 0;     // slabs retained + large allocations alive
        std::size_t liveBytes = 0;         // charged allocation sizes, not logical KV bytes
        std::size_t cachedBytes = 0;       // freed / unused slab slots available for reuse
        std::size_t internalWasteBytes = 0; // live slots minus requested sizes
        std::size_t largeLiveBytes = 0;    // allocations not served by size classes
        std::uint64_t reusedAllocations = 0;
        std::uint64_t systemAllocations = 0;
    };

    SlabResource() = default;
    SlabResource(const SlabResource&) = delete;
    SlabResource& operator=(const SlabResource&) = delete;
    ~SlabResource() override;

    Stats stats() const;

private:
    struct FreeBlock { FreeBlock* next; };
    struct Class {
        std::size_t slotBytes;
        FreeBlock* virginHead = nullptr;   // never allocated from this slab
        FreeBlock* recycledHead = nullptr; // returned by a real deallocation
        std::size_t totalBytes = 0;
        std::size_t liveBytes = 0;
        std::size_t requestedLiveBytes = 0;
    };

    static constexpr std::size_t kSlabBytes = 4096;
    static constexpr std::size_t kMaxPooledBytes = 512;
    static constexpr std::size_t kMaxPooledAlignment = alignof(std::max_align_t);

    mutable std::mutex mutex_;
    std::array<Class, 5> classes_{{{32}, {64}, {128}, {256}, {512}}};
    std::vector<void*> slabs_;
    std::size_t largeLiveBytes_ = 0;
    std::uint64_t reusedAllocations_ = 0;
    std::uint64_t systemAllocations_ = 0;

    void refill(Class& sizeClass);

    void* do_allocate(std::size_t bytes, std::size_t alignment) override;
    void do_deallocate(void* address, std::size_t bytes, std::size_t alignment) override;
    bool do_is_equal(const std::pmr::memory_resource& other) const noexcept override {
        return this == &other;
    }
};

#endif
