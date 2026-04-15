#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "  ┌──────────────────────────────────────────────┐"
echo "  │      Trading Bot — First-Time Setup          │"
echo "  │                                              │"
echo "  │  This will get you from zero to running.     │"
echo "  │  Everything here uses paper money only —     │"
echo "  │  no real dollars at risk.                    │"
echo "  └──────────────────────────────────────────────┘"
echo ""

# ── Step 1: Python version ──────────────────────────────────────────────

echo "Step 1 of 5: Checking Python"
echo "  The bot needs Python 3.11 or newer."
echo ""

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
    echo "  ✗ Python 3.11+ is required but wasn't found on your system."
    echo ""
    echo "  To install it on macOS:"
    echo "    brew install python@3.11"
    echo ""
    echo "  Then run this script again."
    exit 1
fi
echo "  ✓ Found $PYTHON ($($PYTHON --version))"

# ── Step 2: Install dependencies ────────────────────────────────────────

echo ""
echo "─────────────────────────────────────────────────"
echo ""
echo "Step 2 of 5: Installing Python packages"
echo "  This installs the libraries the bot needs —"
echo "  stock data, math tools, and the Alpaca SDK."
echo ""

$PYTHON -m pip install -r requirements.txt --quiet 2>&1 | tail -1
echo "  ✓ All packages installed"

# ── Step 3: Alpaca API keys ─────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────────────────"
echo ""
echo "Step 3 of 5: Connecting to Alpaca"
echo ""
echo "  Alpaca is the broker this bot trades through."
echo "  You need a free paper trading account — this uses"
echo "  simulated money so nothing real is at risk."
echo ""

if [ -n "${ALPACA_API_KEY:-}" ] && [ -n "${ALPACA_API_SECRET:-}" ]; then
    echo "  ✓ Your Alpaca keys are already configured."
else
    echo "  To get your API keys:"
    echo ""
    echo "    1. Go to https://app.alpaca.markets/signup"
    echo "       (sign up if you haven't — it's free, no deposit needed)"
    echo ""
    echo "    2. Once logged in, switch to 'Paper Trading' in the left sidebar"
    echo ""
    echo "    3. Click 'API Keys' and then 'Generate New Key'"
    echo ""
    echo "    4. Copy the Key and Secret — you'll paste them below"
    echo ""

    read -rp "  Paste your API Key here (or press Enter to skip): " api_key

    if [ -z "$api_key" ]; then
        echo ""
        echo "  Skipped for now. You can set up keys later by adding these"
        echo "  two lines to your ~/.zshrc (or ~/.bashrc) file:"
        echo ""
        echo "    export ALPACA_API_KEY=\"your-key\""
        echo "    export ALPACA_API_SECRET=\"your-secret\""
        echo ""
        echo "  Then restart your terminal and run ./setup.sh again."
    else
        read -rp "  Paste your API Secret here: " api_secret

        if [ -z "$api_secret" ]; then
            echo "  ✗ Secret can't be empty. Run setup again when you have both."
        else
            export ALPACA_API_KEY="$api_key"
            export ALPACA_API_SECRET="$api_secret"

            SHELL_PROFILE=""
            if [ -f "$HOME/.zshrc" ]; then
                SHELL_PROFILE="$HOME/.zshrc"
            elif [ -f "$HOME/.bashrc" ]; then
                SHELL_PROFILE="$HOME/.bashrc"
            elif [ -f "$HOME/.bash_profile" ]; then
                SHELL_PROFILE="$HOME/.bash_profile"
            fi

            if [ -n "$SHELL_PROFILE" ]; then
                echo "" >> "$SHELL_PROFILE"
                echo "# Alpaca Paper Trading API (added by trading bot setup)" >> "$SHELL_PROFILE"
                echo "export ALPACA_API_KEY=\"$api_key\"" >> "$SHELL_PROFILE"
                echo "export ALPACA_API_SECRET=\"$api_secret\"" >> "$SHELL_PROFILE"
                echo ""
                echo "  ✓ Keys saved to $SHELL_PROFILE"
                echo "    They'll load automatically every time you open a terminal."
            else
                echo ""
                echo "  ⚠ Couldn't find your shell profile. Add these lines manually"
                echo "    to ~/.zshrc or ~/.bashrc:"
                echo ""
                echo "    export ALPACA_API_KEY=\"$api_key\""
                echo "    export ALPACA_API_SECRET=\"$api_secret\""
            fi
        fi
    fi
fi

# ── Step 4: Verify connection ───────────────────────────────────────────

echo ""
echo "─────────────────────────────────────────────────"
echo ""
echo "Step 4 of 5: Testing the connection"
echo ""

if [ -n "${ALPACA_API_KEY:-}" ] && [ -n "${ALPACA_API_SECRET:-}" ]; then
    if $PYTHON -c "
import alpaca_trade_api as tradeapi
try:
    client = tradeapi.REST(
        '${ALPACA_API_KEY}', '${ALPACA_API_SECRET}',
        'https://paper-api.alpaca.markets', api_version='v2'
    )
    acct = client.get_account()
    value = float(acct.portfolio_value)
    cash = float(acct.cash)
    print(f'  ✓ Connected to Alpaca paper trading')
    print(f'    Portfolio value: \${value:,.2f}')
    print(f'    Cash available:  \${cash:,.2f}')
    print()
    print(f'    This is simulated money — not real.')
except Exception as e:
    print(f'  ✗ Connection failed: {e}')
    print()
    print(f'    Common fixes:')
    print(f'    - Make sure you copied the PAPER trading keys, not live')
    print(f'    - Regenerate the keys if they were just created (sometimes takes a moment)')
" 2>/dev/null; then
        :
    else
        echo "  ✗ Couldn't connect. The Alpaca Python SDK may not be installed correctly."
        echo "    Try: $PYTHON -m pip install alpaca-trade-api"
    fi
else
    echo "  ⚠ Skipped — no API keys configured yet."
    echo "    The bot can still run in simulated mode (no broker connection),"
    echo "    but it won't be able to place orders or check real prices."
fi

# ── Step 5: Run tests ──────────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────────────────"
echo ""
echo "Step 5 of 5: Running tests"
echo "  Making sure everything works..."
echo ""

if $PYTHON test_simulation.py 2>&1 | grep -q "ALL TESTS PASSED"; then
    echo "  ✓ All tests passed — the system is working correctly."
else
    echo "  ✗ Some tests failed. This might be a Python version issue."
    echo "    Run '$PYTHON test_simulation.py' to see details."
fi

# ── Done ────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Setup complete!"
echo ""
echo "  What to do next:"
echo ""
echo "  1. See what the scanner finds today:"
echo "     $PYTHON orchestrator.py --scan"
echo ""
echo "  2. Check the portfolio dashboard:"
echo "     $PYTHON orchestrator.py --report"
echo ""
echo "  3. Run the full pipeline (this will place paper trades):"
echo "     $PYTHON orchestrator.py"
echo ""
echo "  4. Read CONCEPTS.md to understand how the system thinks"
echo "     about risk, position sizing, and strategy selection."
echo ""
echo "  5. To set up automated daily trading, see:"
echo "     docs/SETUP-GUIDE.md"
echo ""
echo "═══════════════════════════════════════════════════"
echo ""
