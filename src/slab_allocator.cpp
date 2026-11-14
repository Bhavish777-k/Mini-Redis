#include "slab_allocator.h"

#include <algorithm>
#include <new>

SlabResource::~SlabResource() {
    // std::pmr containers must be destroyed before their resource.
    for (void* slab : slabs_) {
        ::operator delete(slab, std::align_val_t(kMaxPooledAlignment));
    }
}

void SlabResource::refill(Class& c) {
    void* slab = ::operator new(kSlabBytes, std::align_val_t(kMaxPooledAlignment));
    try {
        slabs_.push_back(slab);
    } catch (...) {
        ::operator delete(slab, std::align_val_t(kMaxPooledAlignment));
        throw;
    }

    auto* begin = static_cast<std::byte*>(slab);
    for (std::size_t pos = 0; pos + c.slotBytes <= kSlabBytes; pos += c.slotBytes) {
        auto* block = reinterpret_cast<FreeBlock*>(begin + pos);
        block->next = c.virginHead;
        c.virginHead = block;
    }
    c.totalBytes += kSlabBytes;
    ++systemAllocations_;
}

void* SlabResource::do_allocate(std::size_t bytes, std::size_t alignment) {
    if (bytes <= kMaxPooledBytes && alignment <= kMaxPooledAlignment) {
        const std::size_t required = std::max(bytes, sizeof(FreeBlock));
        std::lock_guard<std::mutex> lock(mutex_);
        for (auto& c : classes_) {
            if (required > c.slotBytes) continue;
            if (!c.recycledHead && !c.virginHead) refill(c);
            FreeBlock* block;
            if (c.recycledHead) {
                block = c.recycledHead;
                c.recycledHead = block->next;
                ++reusedAllocations_;
            } else {
                block = c.virginHead;
                c.virginHead = block->next;
            }
            c.liveBytes += c.slotBytes;
            c.requestedLiveBytes += bytes;
            return block;
        }
    }

    // Large and over-aligned allocations are returned to the OS allocator immediately.
    void* ptr = alignment > kMaxPooledAlignment
        ? ::operator new(bytes, std::align_val_t(alignment))
        : ::operator new(bytes);
    std::lock_guard<std::mutex> lock(mutex_);
    largeLiveBytes_ += bytes;
    ++systemAllocations_;
    return ptr;
}

void SlabResource::do_deallocate(void* ptr, std::size_t bytes, std::size_t alignment) {
    if (!ptr) return;
    if (bytes <= kMaxPooledBytes && alignment <= kMaxPooledAlignment) {
        const std::size_t required = std::max(bytes, sizeof(FreeBlock));
        std::lock_guard<std::mutex> lock(mutex_);
        for (auto& c : classes_) {
            if (required > c.slotBytes) continue;
            auto* block = static_cast<FreeBlock*>(ptr);
            block->next = c.recycledHead;
            c.recycledHead = block;
            c.liveBytes -= c.slotBytes;
            c.requestedLiveBytes -= bytes;
            return;
        }
    }

    {
        std::lock_guard<std::mutex> lock(mutex_);
        largeLiveBytes_ -= bytes;
    }
    if (alignment > kMaxPooledAlignment)
        ::operator delete(ptr, std::align_val_t(alignment));
    else
        ::operator delete(ptr);
}

SlabResource::Stats SlabResource::stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    Stats result;
    result.largeLiveBytes = largeLiveBytes_;
    result.reservedBytes = largeLiveBytes_;
    result.liveBytes = largeLiveBytes_;
    for (const auto& c : classes_) {
        result.reservedBytes += c.totalBytes;
        result.liveBytes += c.liveBytes;
        result.cachedBytes += c.totalBytes - c.liveBytes;
        result.internalWasteBytes += c.liveBytes - c.requestedLiveBytes;
    }
    result.reusedAllocations = reusedAllocations_;
    result.systemAllocations = systemAllocations_;
    return result;
}
