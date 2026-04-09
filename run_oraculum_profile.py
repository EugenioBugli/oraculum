"""Entry point with detailed memory and frame profiling."""
import os
import sys
import tracemalloc
import gc
from collections import deque
from datetime import datetime

# Start tracing
tracemalloc.start()
gc.set_debug(gc.DEBUG_SAVEALL)

from src.viewer import main

def print_memory_stats(label=""):
    """Print current memory usage and top allocations."""
    current, peak = tracemalloc.get_traced_memory()
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Memory {label}")
    print(f"  Current: {current / 1024 / 1024:.1f} MB | Peak: {peak / 1024 / 1024:.1f} MB")

    # Top 3 allocations
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')[:3]
    print("  Top allocations:")
    for stat in top_stats:
        print(f"    {stat}")

if __name__ == "__main__":
    print("[*] Starting oraculum with memory profiling...")
    print("[*] Press Ctrl+C to stop and see memory report")

    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        print_memory_stats("at exit")

        # Check for unreachable objects
        gc_objects = len(gc.garbage)
        if gc_objects > 0:
            print(f"\n[WARNING] {gc_objects} unreachable objects found!")
            print("Top types:")
            from collections import Counter
            types = Counter(type(obj).__name__ for obj in gc.garbage[:100])
            for typ, count in types.most_common(5):
                print(f"  {typ}: {count}")

        tracemalloc.stop()
