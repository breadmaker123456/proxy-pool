import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

from glider_config import (
    check_interval as load_check_interval,
    ensure_config_dir,
    listen_address,
    strategy as load_strategy,
)


def run_command(command, capture_output=False):
    try:
        process = subprocess.run(
            command,
            shell=True,
            check=True,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            text=True,
        )
        return process.stdout if capture_output else True
    except subprocess.CalledProcessError as exc:
        print(f"Error executing command: {command}")
        print(f"Error output: {exc.stderr}")
        return False


def build_base_config(listen_value: str, strategy_value: str, interval_value: int) -> str:
    return f"""# Verbose mode, print logs
verbose=true

# 监听地址
listen={listen_value}

# Round Robin mode: rr
# High Availability mode: ha
strategy={strategy_value}

# forwarder health check
check=http://www.msftconnecttest.com/connecttest.txt#expect=200

# check interval(seconds)
checkinterval={interval_value}

"""


def update_glider_conf(forward_content: str, glider_conf_path: Path, base_config: str):
    glider_conf_path.parent.mkdir(parents=True, exist_ok=True)

    if not glider_conf_path.exists():
        with open(glider_conf_path, 'w', encoding='utf-8') as file:
            file.write(base_config + forward_content)
        return

    with open(glider_conf_path, 'r', encoding='utf-8') as file:
        content = file.read()

    if re.search(r'forward=.*', content):
        new_content = re.sub(r'(forward=.*\n)+', forward_content, content)
    else:
        new_content = content.rstrip() + '\n' + forward_content

    with open(glider_conf_path, 'w', encoding='utf-8') as file:
        file.write(new_content)


def main():
    current_dir = Path(__file__).parent.absolute()
    config_dir = ensure_config_dir(current_dir)
    glider_conf_path = config_dir / "glider.conf"
    base_config = build_base_config(
        listen_address("10707"),
        load_strategy(),
        load_check_interval(30),
    )

    collector_path = current_dir / "aggregator" / "subscribe" / "collect.py"
    parse_path = current_dir / "parse.py"
    clash_yaml_path = current_dir / "aggregator" / "data" / "clash.yaml"

    clash_yaml_path.parent.mkdir(parents=True, exist_ok=True)

    if not clash_yaml_path.exists():
        with open(clash_yaml_path, 'w', encoding='utf-8') as file:
            yaml.safe_dump({'proxies': []}, file, allow_unicode=True)

    if not collector_path.exists():
        print(f"Error: Collector script not found at {collector_path}")
        sys.exit(1)

    if not parse_path.exists():
        print(f"Error: Parser script not found at {parse_path}")
        sys.exit(1)

    print("Running collector...")
    collect_command = f"python -u {collector_path} -s"
    if not run_command(collect_command):
        sys.exit(1)

    if not clash_yaml_path.exists():
        print(f"Error: clash.yaml was not generated at {clash_yaml_path}")
        sys.exit(1)

    print("\nParsing collected data...")
    parse_command = f"python {parse_path} {clash_yaml_path}"
    forward_content = run_command(parse_command, capture_output=True)
    if not forward_content:
        sys.exit(1)

    print("\nUpdating glider configuration...")
    update_glider_conf(forward_content, glider_conf_path, base_config)

    print("\nProcess completed successfully!")


if __name__ == "__main__":
    main()
