"""Entry point with memory profiling — for debugging memory leaks."""
import tracemalloc
from src.viewer import main

if __name__ == "__main__":
    # Start tracing memory allocations
    tracemalloc.start()

    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        # Print memory stats before exit
        current, peak = tracemalloc.get_traced_memory()
        print(f"\n[Memory] Current: {current / 1024 / 1024:.1f} MB, Peak: {peak / 1024 / 1024:.1f} MB")
        tracemalloc.stop()
