"""
Tests for universe.py: ensure_cache timeout, fallback, and SIGALRM restoration.
"""

import json
import os
import signal
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


print("=" * 70)
print("  UNIVERSE CACHE TESTS")
print("=" * 70)

# ── Test 1: Fresh cache returns immediately ──
print("\n── Test 1: Fresh cache returned without network call ──")

tmpdir = tempfile.mkdtemp(prefix="trading_test_universe_")
cache_path = Path(tmpdir) / ".universe_cache.json"
fresh_cache = {
    "tickers": ["AAPL", "MSFT"],
    "sector_map": {"AAPL": "TECH", "MSFT": "TECH"},
    "etfs": ["SPY"],
    "metadata": {},
    "built_at": datetime.now().isoformat(),
    "count": 3,
}
with open(cache_path, "w") as f:
    json.dump(fresh_cache, f)

with patch("universe.CACHE_FILE", cache_path), \
     patch("universe.build_universe") as mock_build:
    from universe import ensure_cache
    result = ensure_cache()
    check("Returns cached data", result is not None)
    check("Count matches", result["count"] == 3)
    check("build_universe NOT called", not mock_build.called)

# ── Test 2: Stale cache triggers rebuild ──
print("\n── Test 2: Stale cache triggers rebuild ──")
stale_cache = dict(fresh_cache)
stale_cache["built_at"] = (datetime.now() - timedelta(days=10)).isoformat()
with open(cache_path, "w") as f:
    json.dump(stale_cache, f)

rebuilt = dict(fresh_cache)
rebuilt["count"] = 99
rebuilt["built_at"] = datetime.now().isoformat()

with patch("universe.CACHE_FILE", cache_path), \
     patch("universe.build_universe", return_value=rebuilt) as mock_build:
    result = ensure_cache()
    check("build_universe called for stale cache", mock_build.called)
    check("Returns rebuilt data", result["count"] == 99)

# ── Test 3: Timeout falls back to stale cache ──
print("\n── Test 3: Timeout falls back to stale cache ──")
stale_cache["built_at"] = (datetime.now() - timedelta(days=10)).isoformat()
with open(cache_path, "w") as f:
    json.dump(stale_cache, f)

def _slow_build(**kwargs):
    time.sleep(60)
    return fresh_cache

with patch("universe.CACHE_FILE", cache_path), \
     patch("universe.build_universe", side_effect=_slow_build):
    result = ensure_cache()
    check("Returns stale cache on timeout", result is not None)
    check("Stale cache has original count", result["count"] == 3)

# ── Test 4: SIGALRM handler is restored ──
print("\n── Test 4: SIGALRM handler restored after ensure_cache ──")
sentinel = {"called": False}

def _custom_handler(signum, frame):
    sentinel["called"] = True

signal.signal(signal.SIGALRM, _custom_handler)

with patch("universe.CACHE_FILE", cache_path):
    # Fresh cache — no alarm needed, but handler should still be restored
    stale_cache["built_at"] = datetime.now().isoformat()
    with open(cache_path, "w") as f:
        json.dump(stale_cache, f)
    ensure_cache()

current_handler = signal.getsignal(signal.SIGALRM)
check("SIGALRM handler restored", current_handler is _custom_handler)
signal.signal(signal.SIGALRM, signal.SIG_DFL)

# ── Test 5: No cache at all returns None ──
print("\n── Test 5: No cache + failed build returns None ──")
no_cache_path = Path(tmpdir) / ".no_exist_cache.json"

with patch("universe.CACHE_FILE", no_cache_path), \
     patch("universe.build_universe", side_effect=Exception("network down")):
    result = ensure_cache()
    check("Returns None when no cache and build fails", result is None)

# ── Test 6: Cache file gets 0o600 after build_universe writes ──
print("\n── Test 6: Cache file permissions after build_universe ──")
import universe
perm_cache = Path(tmpdir) / ".perm_cache.json"
# Patch CACHE_FILE to our temp path, then call build_universe with mocked network
with patch("universe.CACHE_FILE", perm_cache), \
     patch("universe._fetch_sp500", return_value=[{"ticker": "AAPL", "name": "Apple", "sector": "TECH"}]), \
     patch("universe._fetch_nasdaq100", return_value=[]), \
     patch("universe._filter_by_liquidity", return_value=[{"ticker": "AAPL", "name": "Apple", "sector": "TECH", "avg_volume": 1000000, "last_price": 150.0}]):
    universe.build_universe(force_refresh=True)
mode = os.stat(perm_cache).st_mode & 0o777
check("Cache file has 0o600 permissions", mode == 0o600)

# Cleanup
import shutil
shutil.rmtree(tmpdir, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
if failed == 0:
    print(f"  ALL {passed} TESTS PASSED")
else:
    print(f"  {passed} PASSED, {failed} FAILED")
print("=" * 70)
print()

sys.exit(1 if failed > 0 else 0)
