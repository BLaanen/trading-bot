#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "  ┌──────────────────────────────────────┐"
echo "  │     Trading Bot — First-Time Setup   │"
echo "  └──────────────────────────────────────┘"
echo ""

# ── Step 1: Python version ──────────────────────────────────────────────

echo "Step 1/5: Checking Python..."

PYTHON=""
for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  ✗ Python 3.11+ required but not found."
    echo "    Install it: brew install python@3.11"
    exit 1
fi
echo "  ✓ Found $PYTHON ($($PYTHON --version))"

# ── Step 2: Install dependencies ────────────────────────────────────────

echo ""
echo "Step 2/5: Installing dependencies..."
$PYTHON -m pip install -r requirements.txt --quiet 2>&1 | tail -1
echo "  ✓ Dependencies installed"

# ── Step 3: Alpaca API keys ─────────────────────────────────────────────

echo ""
echo "Step 3/5: Alpaca API keys"
echo ""
echo "  This bot uses Alpaca's PAPER trading API (not real money)."
echo "  If you don't have an account yet:"
echo "    1. Go to https://app.alpaca.markets/signup"
echo "    2. Sign up (free, no deposit needed for paper trading)"
echo "    3. Go to Paper Trading > API Keys > Generate New Key"
echo ""

if [ -n "${ALPACA_API_KEY:-}" ] && [ -n "${ALPACA_API_SECRET:-}" ]; then
    echo "  ✓ ALPACA_API_KEY is already set in your environment"
    echo "  ✓ ALPACA_API_SECRET is already set in your environment"
else
    echo "  Your API keys need to be exported in your shell profile."
    echo ""

    SHELL_PROFILE=""
    if [ -f "$HOME/.zshrc" ]; then
        SHELL_PROFILE="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        SHELL_PROFILE="$HOME/.bashrc"
    elif [ -f "$HOME/.bash_profile" ]; then
        SHELL_PROFILE="$HOME/.bash_profile"
    fi

    read -rp "  Enter your Alpaca API Key: " api_key
    read -rp "  Enter your Alpaca API Secret: " api_secret

    if [ -z "$api_key" ] || [ -z "$api_secret" ]; then
        echo ""
        echo "  ⚠ Skipped — you can add them later to $SHELL_PROFILE:"
        echo "    export ALPACA_API_KEY=\"your-key\""
        echo "    export ALPACA_API_SECRET=\"your-secret\""
    else
        export ALPACA_API_KEY="$api_key"
        export ALPACA_API_SECRET="$api_secret"

        if [ -n "$SHELL_PROFILE" ]; then
            echo "" >> "$SHELL_PROFILE"
            echo "# Alpaca Paper Trading API (added by trading bot setup)" >> "$SHELL_PROFILE"
            echo "export ALPACA_API_KEY=\"$api_key\"" >> "$SHELL_PROFILE"
            echo "export ALPACA_API_SECRET=\"$api_secret\"" >> "$SHELL_PROFILE"
            echo "  ✓ Keys saved to $SHELL_PROFILE"
        else
            echo "  ⚠ Could not find shell profile. Add these manually:"
            echo "    export ALPACA_API_KEY=\"$api_key\""
            echo "    export ALPACA_API_SECRET=\"$api_secret\""
        fi
    fi
fi

# ── Step 4: Verify connection ───────────────────────────────────────────

echo ""
echo "Step 4/5: Verifying Alpaca connection..."

if [ -n "${ALPACA_API_KEY:-}" ] && [ -n "${ALPACA_API_SECRET:-}" ]; then
    if $PYTHON -c "
import alpaca_trade_api as tradeapi
client = tradeapi.REST('$ALPACA_API_KEY', '$ALPACA_API_SECRET', 'https://paper-api.alpaca.markets', api_version='v2')
acct = client.get_account()
print(f'  ✓ Connected — Paper account: \${float(acct.portfolio_value):,.2f} portfolio value')
" 2>/dev/null; then
        :
    else
        echo "  ✗ Connection failed — check your API keys"
        echo "    Make sure you're using Paper Trading keys, not Live"
    fi
else
    echo "  ⚠ Skipped — no API keys set yet"
fi

# ── Step 5: Run tests ──────────────────────────────────────────────────

echo ""
echo "Step 5/5: Running tests..."

if $PYTHON test_simulation.py 2>&1 | grep -q "ALL TESTS PASSED"; then
    echo "  ✓ Simulation tests passed"
else
    echo "  ✗ Simulation tests failed — check output above"
fi

# ── Done ────────────────────────────────────────────────────────────────

echo ""
echo "  ┌──────────────────────────────────────┐"
echo "  │           Setup Complete!            │"
echo "  └──────────────────────────────────────┘"
echo ""
echo "  Try these commands:"
echo "    $PYTHON orchestrator.py --scan      # See today's signals"
echo "    $PYTHON orchestrator.py --report    # Portfolio dashboard"
echo "    $PYTHON orchestrator.py --edge      # Strategy performance"
echo ""
echo "  To run the full pipeline (places paper orders):"
echo "    $PYTHON orchestrator.py"
echo ""
echo "  To set up automated daily trading, see docs/SETUP-GUIDE.md"
echo ""
