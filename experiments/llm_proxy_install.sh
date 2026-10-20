#!/usr/bin/env bash
# 在其他 Linux 机器上部署同样的「域名透明接管」
# 前提: 把 llm_proxy.py 和本脚本放在同一目录，然后 sudo bash llm_proxy_install.sh
# 作用: 客户端无需改动任何 base_url，本机发往 http://llmapi.evolventapi.com 的
#       请求自动剥离 store 等上游不支持的参数再转发。
set -e
[[ $EUID -ne 0 ]] && { echo "请用 sudo 运行"; exit 1; }

DOMAIN="llmapi.evolventapi.com"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROXY="$SCRIPT_DIR/llm_proxy.py"
PY="$(command -v python3)"
[[ -f "$PROXY" ]] || { echo "找不到 $PROXY"; exit 1; }

# 解析真实 IP（DoH，绕过本机 hosts）
IPS=$(curl -s --max-time 8 "https://dns.alidns.com/resolve?name=$DOMAIN&type=A" \
      | python3 -c "import json,sys; print(','.join(a['data'] for a in json.load(sys.stdin).get('Answer',[]) if a.get('type')==1))" 2>/dev/null || true)
[[ -z "$IPS" ]] && IPS="8.221.109.61,43.112.112.9"   # DoH 失败时的兜底
echo "上游真实IP: $IPS"

echo "1. 安装 systemd 服务..."
tee /etc/systemd/system/llm-api-proxy.service > /dev/null <<EOF
[Unit]
Description=LLM API local transparent proxy (strips incompatible params) for $DOMAIN
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$PY $PROXY
Environment=HOST=127.0.0.1
Environment=PORT=80
Environment=UPSTREAM_HOST=$DOMAIN
Environment=UPSTREAM_IPS=$IPS
Restart=always
RestartSec=2
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now llm-api-proxy.service
sleep 2
systemctl is-active llm-api-proxy.service || { journalctl -u llm-api-proxy -n 20 --no-pager; exit 1; }

echo "2. 添加 /etc/hosts 接管条目..."
grep -q "^127\.0\.0\.1 $DOMAIN$" /etc/hosts || \
  printf '\n# llm-api-proxy: 本机接管 %s（删除此行和下面一行即可恢复）\n127.0.0.1 %s\n' "$DOMAIN" "$DOMAIN" >> /etc/hosts

echo "3. 验证..."
curl -s --max-time 20 "http://$DOMAIN/v1/models" | head -c 60; echo
echo "完成。卸载: sudo bash $SCRIPT_DIR/llm_proxy_uninstall.sh"
