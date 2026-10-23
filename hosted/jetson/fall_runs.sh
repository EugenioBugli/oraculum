#!/bin/bash
# Fall analysis runs (1 robot, Box64 booster-motion as run on 2026-10-22). Results: ~/oraculum-sim-arm/logs/falls/summary.txt + per-run logs.
#   ~/oraculum-sim-arm/fall_runs.sh [run names...]   (default: all)
W=$HOME/oraculum-sim-arm
S1=$W/scenes/1v0.yaml
run() { local name=$1; shift; env "$@" RUN_NAME="$name" SCENE="$S1" MON_EVERY=1 "$W/measure_rtf.sh" > "$W/logs/measure_$name.log" 2>&1; }
RUNS=("$@")
for r in A1 C1 B0 B1 B2; do
    [ ${#RUNS[@]} -eq 0 ] || [[ " ${RUNS[*]} " == *" $r "* ]] || continue
    case $r in
        A1) run A1_simreal_gpu SIM_S=60 SCENARIO=sim_real CIRCUS_IMAGES=1 BOOSTER_MOTION=box64 GPU=1 ;;
        C1) run C1_simreal_gpu_noball SIM_S=60 SCENARIO=sim_real CIRCUS_IMAGES=1 BOOSTER_MOTION=box64 GPU=1 "CIRCUS_BALL_POS=0 40 0.11" ;;
        B0) run B0_simfast_control BOOSTER_MOTION=box64 SIM_S=90 ;;
        B1) run B1_simfast_circus1core BOOSTER_MOTION=box64 SIM_S=60 CIRCUS_CPUS=0 ;;   # did not slow it down (RTF 0.56)
        B2) run B2_simfast_robot_cpus${ROBOT_CPUS:-0.6} BOOSTER_MOTION=box64 SIM_S=40 ROBOT_CPUS=${ROBOT_CPUS:-0.6} ;;
    esac
done
