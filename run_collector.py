import subprocess
import sys
import os
import re
import yaml
from pathlib import Path

def run_command(command, capture_output=False):
    try:
        process = subprocess.run(
            command,
            shell=True,
            check=True,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE,
            encoding='utf-8',  # Specify the encoding here
            text=True
        )
        return process.stdout if capture_output else True
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {command}")
        print(f"Error output: {e.stderr}")
        return False

def update_glider_conf(forward_content):
    current_dir = Path(__file__).parent.absolute()
    glider_conf_path = current_dir / "glider" / "glider.conf"

    # 基础配置
    base_config = """# Verbose mode, print logs
verbose=true

# 监听地址
listen=:10707

# Round Robin mode: rr
# High Availability mode: ha
strategy=rr

# forwarder health check
check=http://www.msftconnecttest.com/connecttest.txt#expect=200

# check interval(seconds)
checkinterval=30

"""

    # 确保glider目录存在
    glider_dir = glider_conf_path.parent
    if not glider_dir.exists():
        glider_dir.mkdir(parents=True)

    # 如果配置文件不存在，创建新文件
    if not glider_conf_path.exists():
        with open(glider_conf_path, 'w', encoding='utf-8') as f:
            f.write(base_config + forward_content)
        return

    # 读取现有配置文件
    with open(glider_conf_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 检查是否存在forward配置
    if re.search(r'forward=.*', content):
        # 替换所有现有的forward行
        new_content = re.sub(
            r'(forward=.*\n)+',
            forward_content,
            content
        )
    else:
        # 在文件末尾添加新的forward配置
        new_content = content.rstrip() + '\n' + forward_content

    # 写入更新后的配置
    with open(glider_conf_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

def main():
    # 获取当前脚本所在目录
    current_dir = Path(__file__).parent.absolute()

    # 定义相关路径
    collector_path = current_dir / "aggregator" / "subscribe" / "collect.py"
    parse_path = current_dir / "parse.py"  # parse.py 现在和 run_collector.py 在同一目录
    clash_yaml_path = current_dir / "aggregator" / "data" / "clash.yaml"

    # 确保 aggregator/data 目录存在
    clash_yaml_path.parent.mkdir(parents=True, exist_ok=True)

    # 如果 clash.yaml 不存在，创建一个包含基本结构的文件
    if not clash_yaml_path.exists():
        initial_config = {
            'proxies': []
        }
        with open(clash_yaml_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(initial_config, f, allow_unicode=True)

    # 检查文件是否存在
    if not collector_path.exists():
        print(f"Error: Collector script not found at {collector_path}")
        sys.exit(1)

    if not parse_path.exists():
        print(f"Error: Parser script not found at {parse_path}")
        sys.exit(1)

    # 1. 运行收集器脚本
    print("Running collector...")
    collect_command = f"python -u {collector_path} -s"
    if not run_command(collect_command):
        sys.exit(1)

    # 确认clash.yaml文件已生成
    if not clash_yaml_path.exists():
        print(f"Error: clash.yaml was not generated at {clash_yaml_path}")
        sys.exit(1)

    # 2. 运行解析器脚本并捕获输出
    print("\nParsing collected data...")
    parse_command = f"python {parse_path} {clash_yaml_path}"
    forward_content = run_command(parse_command, capture_output=True)
    if not forward_content:
        sys.exit(1)

    # 3. 更新 glider.conf
    print("\nUpdating glider configuration...")
    update_glider_conf(forward_content)

    print("\nProcess completed successfully!")

if __name__ == "__main__":
    main()
