#!/bin/bash
# Quick memory test — runs app for 30 seconds and monitors memory

echo "Starting oraculum memory test (30 seconds)..."
echo "Watch the memory column in another terminal with: watch -n 0.5 'ps aux | grep python | grep oraculum'"
echo ""

(timeout 30s python run_oraculum.py 2>&1 | grep -v "matplotlib\|INFO") &
PID=$!

sleep 2
echo "Process started (PID $PID)"
echo ""

# Monitor memory
for i in {1..30}; do
    if ps -p $PID > /dev/null 2>&1; then
        MEM=$(ps aux | grep "PID $PID" | grep python | awk '{print $6}' | head -1)
        if [ -z "$MEM" ]; then
            MEM=$(ps -p $PID -o rss=)
        fi
        MEM_MB=$((${MEM:-0} / 1024))
        echo "[$(printf '%2d' $i)s] Memory: ${MEM_MB}MB"
        sleep 1
    else
        echo "[ENDED] Process exited after $((i-1)) seconds"
        exit 0
    fi
done

wait $PID
echo "[DONE] Test complete"
