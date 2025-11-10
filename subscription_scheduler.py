#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# argparse removed — using top-of-file variables for configuration
import base64
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from glider_config import (
    check_interval as load_check_interval,
    ensure_config_dir,
    listen_address,
    strategy as load_strategy,
)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
try:
    import requests
except ImportError:
    requests = None

# ==========================
# Configurable variables
# Edit these to control behavior without CLI args
# ==========================
BASE_DIR = Path(__file__).parent.absolute()
CONFIG_DIR = ensure_config_dir(BASE_DIR)
SUBSCRIPTIONS_FILE = os.environ.get('SUBSCRIPTIONS_FILE', 'subscriptions.txt')  # path to txt file listing subscription URLs
CONFIG_OUTPUT = CONFIG_DIR / 'glider.subscription.conf'  # output glider config path
LISTEN = listen_address("10710")  # listen address for glider (e.g., ':10707' or '127.0.0.1:10809')
INTERVAL_SECONDS = max(60, _env_int('SUBSCRIPTION_REFRESH_INTERVAL', 6000))  # refresh interval seconds
GLIDER_BINARY = str(Path('glider') / ('glider.exe' if os.name == 'nt' else 'glider'))  # path to glider binary
STRATEGY = load_strategy()
CHECK_INTERVAL_SECONDS = load_check_interval(300)
FILE_WATCH_INTERVAL = max(5, _env_int('SUBSCRIPTIONS_WATCH_INTERVAL', 15))
RUN_ONCE = False  # set True to run once and exit
DRY_RUN = False   # set True to fetch/parse only (no write/start)

# Per-forwarder testing configuration
TEST_EACH_FORWARD = True  # test each imported node for usability
TEST_URL = 'http://www.msftconnecttest.com/connecttest.txt#expect=200'  # use Google to test
TEST_EXPECT_STATUSES = (204, 200)  # acceptable HTTP statuses
TEST_TIMEOUT = 8  # seconds
TEST_LISTEN_HOST = '127.0.0.1'
TEST_START_PORT = 18081  # starting port for temporary glider listeners during tests
TEST_MAX_WORKERS = 20  # number of threads to test forwarders concurrently

# Health check URL used inside generated glider config
HEALTHCHECK_URL = 'http://www.msftconnecttest.com/connecttest.txt#expect=200'


def _ensure_requests():
    if requests is None:
        print("Error: requests is required. Please 'pip install -r requirements.txt'", file=sys.stderr)
        sys.exit(1)


def _b64_decode(s: str) -> bytes:
    s = s.strip().replace('-', '+').replace('_', '/')
    padding = (-len(s)) % 4
    return base64.b64decode(s + ('=' * padding))


def _vmess_from_base64(uri: str) -> str:
    payload = uri[len('vmess://'):]  # strip scheme
    try:
        raw = _b64_decode(payload).decode('utf-8', errors='ignore')
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError('Invalid vmess JSON payload')
        server = str(data.get('add', '')).strip()
        port = str(data.get('port', '')).strip()
        uuid = str(data.get('id', '')).strip()
        alter_id = str(data.get('aid', '0')).strip() or '0'
        if not (server and port and uuid):
            raise ValueError('Missing required vmess fields (add/port/id)')
        return f"vmess://none:{uuid}@{server}:{port}?alterID={alter_id}"
    except Exception:
        return uri


def parse_txt_content(text: str) -> Tuple[str, int]:
    """Parse plain text subscription content into glider forward lines.
    - Accept ss:// and vmess:// lines
    - Detect and decode base64-encoded blob first (some providers base64-wrap the whole list)
    - Normalize ss:// variants: decode base64 userinfo before '@', and decode fully base64 ss URIs
    """
    def _maybe_decode_base64_blob(s: str) -> str:
        compact = ''.join(s.split())
        if not compact:
            return s
        # Heuristic: must be base64 alphabet
        if not re.fullmatch(r'[A-Za-z0-9+/=_-]+', compact):
            return s
        try:
            decoded = _b64_decode(compact).decode('utf-8', errors='ignore')
            # Only treat as valid if it yields recognizable URIs
            if 'ss://' in decoded or 'vmess://' in decoded:
                return decoded
        except Exception:
            pass
        return s

    def _normalize_ss_uri(uri: str) -> str:
        # Expect uri starts with ss://
        try:
            rest = uri[len('ss://'):]
            # Case A: base64 userinfo before '@' (e.g., ss://BASE64@host:port#tag)
            if '@' in rest:
                userinfo, tail = rest.split('@', 1)
                # If userinfo looks like base64 and does not already contain ':' (common hint)
                if re.fullmatch(r'[A-Za-z0-9+/=_-]+', userinfo) and ':' not in userinfo:
                    try:
                        dec = _b64_decode(userinfo).decode('utf-8', errors='ignore')
                        # Must be method:password
                        if ':' in dec and '@' not in dec:
                            return f"ss://{dec}@{tail}"
                    except Exception:
                        pass
                return uri
            # Case B: fully base64 after scheme (e.g., ss://BASE64#tag)
            base_part = rest.split('#', 1)[0]
            suffix = rest[len(base_part):]  # includes '#' and tag if any
            if re.fullmatch(r'[A-Za-z0-9+/=_-]+', base_part):
                try:
                    dec_full = _b64_decode(base_part).decode('utf-8', errors='ignore')
                    # Expected method:password@host:port[?plugin=...]
                    if ':' in dec_full and '@' in dec_full:
                        return f"ss://{dec_full}{suffix}"
                except Exception:
                    pass
            return uri
        except Exception:
            return uri

    def _parse_lines(s: str) -> List[str]:
        forwards: List[str] = []
        for raw in s.splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('ss://'):
                normalized = _normalize_ss_uri(line)
                forwards.append(f"forward={normalized}")
            elif line.startswith('vmess://'):
                candidate = line if '@' in line else _vmess_from_base64(line)
                forwards.append(f"forward={candidate}")
        return forwards

    # 1) If the whole content is a base64 blob, decode it first
    text_to_parse = _maybe_decode_base64_blob(text)

    # 2) Parse lines
    forwards = _parse_lines(text_to_parse)

    # 3) Fallback: if nothing parsed, try base64-decoding anyway (handles edge cases)
    if not forwards:
        compact = ''.join(text.split())
        try:
            decoded = _b64_decode(compact).decode('utf-8', errors='ignore')
            forwards = _parse_lines(decoded)
        except Exception:
            forwards = []

    out = "\n".join(forwards)
    if out and not out.endswith('\n'):
        out += '\n'
    return out, len(forwards)


def parse_yaml_content(text: str) -> Tuple[str, int]:
    """Use parse.py:parse_config to convert Clash YAML proxies to forward lines."""
    import importlib.util
    current_dir = Path(__file__).parent.absolute()
    parse_path = current_dir / 'parse.py'
    if not parse_path.exists():
        raise FileNotFoundError(f'Parser script not found at {parse_path}')
    data = yaml.safe_load(text) or {}
    proxies = data.get('proxies', [])
    spec = importlib.util.spec_from_file_location('parse_module', str(parse_path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    forward_content = mod.parse_config(proxies)
    return forward_content, len(proxies)


def detect_format_from_response(resp_text: str, resp_ct: str) -> str:
    ct = (resp_ct or '').lower()
    head = next((ln.strip() for ln in resp_text.splitlines() if ln.strip()), '')
    if head.startswith('proxies:'):
        return 'yaml'
    if 'yaml' in ct or 'yml' in ct:
        return 'yaml'
    if 'text/plain' in ct:
        return 'txt'
    return 'txt'


def fetch_and_parse(urls: List[str]) -> Tuple[str, dict]:
    """Fetch all URLs, parse into forward lines, deduplicate, and return combined content and stats."""
    _ensure_requests()
    forwards: List[str] = []
    stats = { 'total_urls': len(urls), 'ok_urls': 0, 'failed_urls': 0, 'entries': 0, 'by_url': {} }

    for url in urls:
        url_stats = { 'count': 0, 'error': None, 'format': None }
        try:
            resp = requests.get(url, timeout=30, verify=False)
            resp.raise_for_status()
            fmt = detect_format_from_response(resp.text, resp.headers.get('Content-Type', ''))
            url_stats['format'] = fmt
            if fmt == 'yaml':
                content, count = parse_yaml_content(resp.text)
            else:
                content, count = parse_txt_content(resp.text)
            if count > 0:
                forwards.extend([ln.strip() for ln in content.splitlines() if ln.strip()])
                url_stats['count'] = count
                stats['ok_urls'] += 1
            else:
                url_stats['error'] = 'No usable entries'
                stats['failed_urls'] += 1
        except Exception as e:
            url_stats['error'] = str(e)
            stats['failed_urls'] += 1
        stats['by_url'][url] = url_stats

    # Deduplicate and normalize
    dedup = []
    seen = set()
    for ln in forwards:
        if not ln.startswith('forward='):
            continue
        if ln not in seen:
            dedup.append(ln)
            seen.add(ln)

    combined = "\n".join(dedup)
    if combined:
        combined += "\n"
    stats['entries'] = len(dedup)
    return combined, stats


def build_base_config(listen: str, strategy_value: str, interval_value: int) -> str:
    return f"""# Verbose mode, print logs
verbose=true

# listen address
listen={listen}

# strategy: rr (round-robin) or ha (high-availability)
strategy={strategy_value}

# forwarder health check
check={HEALTHCHECK_URL}

# check interval(seconds)
checkinterval={interval_value}

"""


def write_config(config_path: Path, forward_content: str, listen: str):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(build_base_config(listen, STRATEGY, CHECK_INTERVAL_SECONDS))
        f.write(forward_content)


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def read_subscriptions_file(path: Path) -> Tuple[List[str], float]:
    if not path.exists():
        return [], 0.0
    urls = []
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f.readlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            urls.append(line)
    return urls, _file_mtime(path)


def run_glider(glider_path: Path, config_path: Path):
    try:
        proc = subprocess.Popen([str(glider_path), '-config', str(config_path)], stdout=None, stderr=None, universal_newlines=True)
        return proc
    except Exception as e:
        print(f"Error starting glider: {e}")
        return None


def kill_glider(proc):
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    except Exception as e:
        print(f"Error killing glider: {e}")


def _choose_test_port(idx: int) -> int:
    return TEST_START_PORT + idx


def _write_temp_test_config(base_dir: Path, port: int, forward_line: str) -> Path:
    cfg_path = base_dir / f'glider.test.{port}.conf'
    content = build_base_config(f'{TEST_LISTEN_HOST}:{port}', STRATEGY, CHECK_INTERVAL_SECONDS) + (forward_line if forward_line.endswith('\n') else forward_line + '\n')
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return cfg_path


def _test_forwarder(glider_path: Path, forward_line: str, idx: int) -> bool:
    """Start a temporary glider with a single forward, then GET Google via HTTP proxy through it."""
    import time as _t
    tmp_cfg = _write_temp_test_config(Path('glider'), _choose_test_port(idx), forward_line)
    port = _choose_test_port(idx)
    proc = None
    try:
        proc = subprocess.Popen([str(glider_path), '-config', str(tmp_cfg)], stdout=None, stderr=None, universal_newlines=True)
        _t.sleep(0.8)  # give glider a moment to start
        proxies = {
            'http': f'http://{TEST_LISTEN_HOST}:{port}',
            'https': f'http://{TEST_LISTEN_HOST}:{port}',
        }
        r = requests.get(TEST_URL, proxies=proxies, timeout=TEST_TIMEOUT)
        return r.status_code in TEST_EXPECT_STATUSES
    except Exception:
        return False
    finally:
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            tmp_cfg.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


def _filter_forwards_with_tests(glider_path: Path, forward_lines: List[str]) -> List[str]:
    if not TEST_EACH_FORWARD:
        return forward_lines
    ok = []
    futures = []
    with ThreadPoolExecutor(max_workers=TEST_MAX_WORKERS) as executor:
        for idx, line in enumerate(forward_lines):
            if not line.startswith('forward='):
                continue
            futures.append((line, executor.submit(_test_forwarder, glider_path, line, idx)))
        for line, fut in futures:
            try:
                if fut.result():
                    ok.append(line)
            except Exception:
                # treat as failed
                pass
    return ok


def _wait_for_next_cycle(subs_path: Path, last_mtime: float) -> float:
    poll = max(1, min(FILE_WATCH_INTERVAL, INTERVAL_SECONDS))
    if poll <= 0:
        poll = 1
    waited = 0
    print(f"[{datetime.now()}] Monitoring {subs_path} (max wait {INTERVAL_SECONDS}s, poll {poll}s)...")
    while waited < INTERVAL_SECONDS:
        remaining = INTERVAL_SECONDS - waited
        sleep_for = poll if remaining > poll else remaining
        time.sleep(sleep_for)
        waited += sleep_for
        current_mtime = _file_mtime(subs_path)
        if current_mtime != last_mtime:
            print(f"[{datetime.now()}] Detected change in {subs_path}; refreshing immediately.")
            return current_mtime
    print(f"[{datetime.now()}] Interval elapsed ({INTERVAL_SECONDS}s); refreshing subscriptions.")
    return _file_mtime(subs_path)


def main():
    # Use top-of-file variables instead of CLI args
    subs_path = Path(SUBSCRIPTIONS_FILE)
    config_path = CONFIG_OUTPUT
    glider_path = Path(GLIDER_BINARY)

    # Validate glider path exists
    if not glider_path.exists():
        print(f"Error: glider executable not found at {glider_path}")
        sys.exit(1)

    # Try to make executable (no-op on Windows)
    try:
        glider_path.chmod(0o755)
    except Exception:
        pass

    urls, last_subs_mtime = read_subscriptions_file(subs_path)
    if not urls:
        print(f"No subscriptions found in {subs_path}. Add URLs (one per line).")
        sys.exit(1)

    # Initial fetch and write config
    forwards, stats = fetch_and_parse(urls)

    # Optional: per-forwarder testing with Google
    forward_lines = [ln.strip() for ln in forwards.splitlines() if ln.strip()]
    tested_lines = _filter_forwards_with_tests(glider_path, forward_lines)
    if tested_lines:
        forwards = "\n".join(tested_lines) + "\n"
    else:
        print("Warning: All tested forwards failed; falling back to untested set.")
    now = datetime.now()
    print(f"[{now}] Fetched subscriptions: ok={stats['ok_urls']}, failed={stats['failed_urls']}, entries={stats['entries']}")

    if DRY_RUN:
        return

    if stats['entries'] > 0:
        write_config(config_path, forwards, LISTEN)
    else:
        if config_path.exists():
            print(f"No usable entries; keeping existing config at {config_path}")
        else:
            print("No usable entries and no existing config. Exiting.")
            sys.exit(1)

    # Start glider
    proc = run_glider(glider_path, config_path)
    if not proc:
        print("Failed to start glider")
        sys.exit(1)

    if RUN_ONCE:
        print("Started glider once; exiting without loop as requested.")
        return

    last_content_hash = hash(forwards)

    def _cleanup(signum, frame):
        print("\nReceived termination signal. Cleaning up...")
        kill_glider(proc)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    while True:
        last_subs_mtime = _wait_for_next_cycle(subs_path, last_subs_mtime)
        urls, last_subs_mtime = read_subscriptions_file(subs_path)
        if not urls:
            print(f"[{datetime.now()}] No subscriptions found; skipping update.")
            continue
        forwards, stats = fetch_and_parse(urls)
        print(f"[{datetime.now()}] Update: ok={stats['ok_urls']}, failed={stats['failed_urls']}, entries={stats['entries']}")
        if stats['entries'] <= 0:
            print("No usable entries; keeping current glider process and config.")
            continue
        # Test updated forwards
        forward_lines = [ln.strip() for ln in forwards.splitlines() if ln.strip()]
        tested_lines = _filter_forwards_with_tests(glider_path, forward_lines)
        if tested_lines:
            forwards = "\n".join(tested_lines) + "\n"
        else:
            print("Warning: All tested forwards failed; keeping current glider process and config.")
            continue
        new_hash = hash(forwards)
        if new_hash == last_content_hash:
            print("Entries unchanged; no restart needed.")
            continue
        # Write and restart
        write_config(config_path, forwards, LISTEN)
        print("Restarting glider...")
        kill_glider(proc)
        proc = run_glider(glider_path, config_path)
        if not proc:
            print("Failed to restart glider; will keep trying next cycle.")
            continue
        last_content_hash = new_hash
        print("Glider restarted with updated config.")


if __name__ == '__main__':
    main()
