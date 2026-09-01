// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <thread>
#include <vector>

namespace
{
std::atomic<int> loadCalls {0};
constexpr long LoadedResult = 37;
}  // namespace

extern "C" long NlLoadLibrary()
{
    ++loadCalls;
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    return LoadedResult;
}

extern "C" long NlEnsureLoaded();

TEST(NavlibLazyLoad, ConcurrentFirstUseLoadsExactlyOnce)
{
    constexpr int ThreadCount = 32;
    std::atomic<bool> start {false};
    std::vector<long> results(ThreadCount, 0);
    std::vector<std::thread> threads;
    threads.reserve(ThreadCount);
    for (int index = 0; index < ThreadCount; ++index) {
        threads.emplace_back([&start, &results, index] {
            while (!start.load(std::memory_order_acquire)) {
                std::this_thread::yield();
            }
            results[index] = NlEnsureLoaded();
        });
    }

    start.store(true, std::memory_order_release);
    for (auto& thread : threads) {
        thread.join();
    }

    EXPECT_EQ(loadCalls.load(), 1);
    for (const long result : results) {
        EXPECT_EQ(result, LoadedResult);
    }
}
