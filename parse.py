import yaml
import json
import argparse
import sys
from pathlib import Path

def parse_config(array: list):
    print(f"Debug: Received {len(array)} proxies to parse", file=sys.stderr)
    ss = []
    vmess = []
    
    # glider支持的ss加密方式
    supported_ciphers = {
        'aes-128-gcm',
        'aes-256-gcm',
        'chacha20-ietf-poly1305',
        'aes-128-ctr',
        'aes-192-ctr',
        'aes-256-ctr',
        'aes-128-cfb',
        'aes-192-cfb',
        'aes-256-cfb',
        'chacha20-ietf',
        'xchacha20-ietf-poly1305'
    }

    for node in array:
        if node['type'] == 'ss':
            # 跳过不支持的加密方式
            if node['cipher'] not in supported_ciphers:
                continue
            node_str = f"{node['type']}://{node['cipher']}:{node['password']}@{node['server']}:{node['port']}#{node['name']}"
            ss.append(node_str)
        elif node['type'] == 'vmess':
            node_str = f"{node['type']}://none:{node['uuid']}@{node['server']}:{node['port']}?alterID={node['alterId']}"
            vmess.append(node_str)
    
    # 构建输出内容
    output = ""
    for node in ss:
        output += f'forward={node}\n'
    for node in vmess:
        output += f'forward={node}\n'
    return output

def main():
    # 创建参数解析器
    parser = argparse.ArgumentParser(description='Parse clash configuration file')
    parser.add_argument('config_path', help='Path to the clash.yaml configuration file')
    
    # 解析命令行参数
    args = parser.parse_args()
    
    # 检查文件是否存在
    config_path = Path(args.config_path)
    if not config_path.exists():
        print(f"Error: File {args.config_path} does not exist", file=sys.stderr)
        sys.exit(1)
        
    try:
        # 读取并解析配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if not config or 'proxies' not in config:
                print("Error: Invalid configuration file format", file=sys.stderr)
                sys.exit(1)
            output = parse_config(config['proxies'])
            print(output, end='')  # 输出到标准输出，供run_collector.py捕获
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()

