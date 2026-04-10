#!/bin/bash
#
# Trading Bot Schedule Manager
#
# Usage:
#   ./schedule.sh status    # Show all 3 agents and their last run
#   ./schedule.sh logs      # Tail the launchd logs
#   ./schedule.sh start     # Load the 3 LaunchAgents (installs the schedule)
#   ./schedule.sh stop      # Unload the 3 LaunchAgents (disables the schedule)
#   ./schedule.sh restart   # Stop then start
#   ./schedule.sh kick NAME # Manually trigger one agent (at_open, monitor, eod)

set -e

AGENTS=(
    "com.bopeterlaanen.trading.at_open"
    "com.bopeterlaanen.trading.monitor"
    "com.bopeterlaanen.trading.eod"
)

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="/Users/bopeterlaanen/trading/logs"

cmd="${1:-status}"

case "$cmd" in
    status)
        echo "══════════════════════════════════════════════════════════════════"
        echo "  TRADING BOT SCHEDULE STATUS"
        echo "══════════════════════════════════════════════════════════════════"
        echo
        for agent in "${AGENTS[@]}"; do
            if launchctl list | grep -q "$agent"; then
                status=$(launchctl list | grep "$agent")
                pid=$(echo "$status" | awk '{print $1}')
                exit=$(echo "$status" | awk '{print $2}')
                echo "  ✓ $agent"
                echo "      PID: $pid    Last exit: $exit"
                log="$LOG_DIR/launchd_$(echo $agent | sed 's/com.bopeterlaanen.trading.//').log"
                if [ -f "$log" ]; then
                    size=$(wc -c < "$log" | tr -d ' ')
                    mtime=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$log")
                    echo "      Log: $size bytes, last modified $mtime"
                fi
            else
                echo "  ✗ $agent (not loaded)"
            fi
            echo
        done
        echo "  Schedules (all CEST):"
        echo "    at_open  → daily 15:25  (trades entry)"
        echo "    monitor  → every 5 min  (position tracking)"
        echo "    eod      → daily 22:10  (learning loop + weekly report)"
        ;;

    logs)
        echo "══════════════════════════════════════════════════════════════════"
        echo "  TAILING LAUNCHD LOGS (Ctrl+C to exit)"
        echo "══════════════════════════════════════════════════════════════════"
        tail -F "$LOG_DIR"/launchd_*.log 2>/dev/null
        ;;

    start)
        echo "Loading 3 LaunchAgents..."
        for agent in "${AGENTS[@]}"; do
            launchctl load -w "$LAUNCH_AGENTS_DIR/$agent.plist" 2>&1 \
                && echo "  ✓ $agent" \
                || echo "  ✗ $agent (may already be loaded)"
        done
        ;;

    stop)
        echo "Unloading 3 LaunchAgents..."
        for agent in "${AGENTS[@]}"; do
            launchctl unload "$LAUNCH_AGENTS_DIR/$agent.plist" 2>&1 \
                && echo "  ✓ $agent" \
                || echo "  ✗ $agent (may not be loaded)"
        done
        ;;

    restart)
        "$0" stop
        "$0" start
        ;;

    kick)
        name="${2:-}"
        if [ -z "$name" ]; then
            echo "Usage: $0 kick {at_open|monitor|eod}"
            exit 1
        fi
        agent="com.bopeterlaanen.trading.$name"
        echo "Triggering $agent..."
        launchctl kickstart -k "gui/$(id -u)/$agent"
        ;;

    *)
        echo "Usage: $0 {status|logs|start|stop|restart|kick NAME}"
        exit 1
        ;;
esac
