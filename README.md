# airProxyPool 代理池
![proxy_config](docs/images/use.png)


用于“代理池”场景：把不同来源、不同格式的节点统一成一个稳定的 SOCKS5 出口。适合爬虫、批量注册（注册机）、自动化任务等需要大量/稳定出站代理的场景。

1) 通过 aggregator 自动扫描与聚合可用节点
2) 使用 glider 将节点统一转换为 SOCKS5 代理供外部访问
3) 自定义“机场”订阅一键转换为 glider 可用的 forward= 节点

- 普通用户：使用“白嫖机场”订阅作为代理池，开箱即用。
- 有追求用户：使用自建订阅或付费机场作为代理池，更干净、更可控。

## 功能特点

- 自动收集与定时更新
- 可用性检测与故障转移
- 支持 SS / VMess
- 统一的 SOCKS5 访问接口
- 支持自定义订阅（机场）→ glider 节点转换（单次或定时轮询）

## 目录
- [通用准备](#通用准备)
- [使用“白嫖机场”订阅作为代理池](#建议小白使用白嫖机场订阅作为代理池)
- [使用自建/付费订阅作为代理池](#有追求使用自建付费订阅作为代理池)

## 通用准备

- 依赖要求
  - Python 3.7+
  - glider 可执行文件

- 创建虚拟环境并安装依赖
```bash
python -m venv venv
pip install -r requirements.txt
```

- 安装 glider（下载与放置）
  - 将可执行文件放到项目 glider/ 目录：
    - Windows: glider/glider.exe（示例下载链接：v0.16.4 32-bit）
      https://github.com/nadoo/glider/releases/download/v0.16.4/glider_0.16.4_windows_386.zip
      解压后重命名为 glider.exe 放到 glider/ 目录
      验证： `./glider/glider.exe -h`

    - macOS（示例，版本号以官方为准）
      ```bash
      # 示例：下载压缩包
      wget https://github.com/nadoo/glider/releases/download/v0.16.3/glider_0.16.3_macos_amd64.tar.gz
      # 解压（文件名以实际下载为准）
      tar -zxf glider_0.16.3_darwin_amd64.tar.gz
      # 移动到项目目录的 glider/
      mv glider_0.16.3_darwin_amd64 glider
      chmod +x glider/glider
      ```

    - Linux（示例，版本号以官方为准）

      ```bash
      wget https://github.com/nadoo/glider/releases/download/v0.16.3/glider_0.16.3_linux_amd64.tar.gz
      tar -zxf glider_0.16.3_linux_amd64.tar.gz
      mv glider_0.16.3_linux_amd64 glider
      chmod +x glider/glider
      ```
- glider 基础配置（glider/glider.conf）（此为示例，脚本会自行创建）
```conf
# Verbose mode, print logs
verbose=true

# 监听地址
listen=:10707

# 负载策略：rr（轮询）/ ha（高可用）
strategy=rr

# 健康检查
check=http://www.msftconnecttest.com/connecttest.txt#expect=200

# 健康检查间隔（秒）
checkinterval=30
```

---

## 使用“白嫖机场”订阅作为代理池

此方式依赖 aggregator（作为 Git 子模块），自动聚合免费节点。

- 初始化 submodule（首次必做）
```bash
git submodule update --init --recursive
```
- 安装 aggregator 依赖（在项目根）
```bash
pip install -r aggregator/requirements.txt
```
- 手动跑一轮采集并写入 glider/glider.conf 的 forward= 段
```bash
python run_collector.py
```
- 守护运行（每 30 分钟刷新并重启 glider 生效）
```bash
python scheduler.py
```
- 默认 SOCKS5：127.0.0.1:10707
- 产物：aggregator/data/clash.yaml（聚合结果），glider/glider.conf（含 forward= 行）


---

## 使用自建/付费订阅作为代理池

此方式不需要 submodule（可忽略 aggregator）。
- 定时轮询（长期自动刷新）：在项目根创建 subscriptions.txt（每行一个订阅 URL），然后运行
```bash
python subscription_scheduler.py
```
- 行为：定时拉取 → 解析为 forward= → 写入 glider/glider.subscription.conf → 启动/重启 glider 使用该配置
- 默认 SOCKS5/http：127.0.0.1:10710



## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=dreammis/airProxyPool&type=Date)](https://star-history.com/#dreammis/airProxyPool&Date)
