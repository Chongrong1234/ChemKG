#!/usr/bin/env bash
# 一键卸载 llmapi.evolventapi.com 的本机域名接管
# 用法: sudo bash llm_proxy_uninstall.sh
set -e
[[ $EUID -ne 0 ]] && { echo "请用 sudo 运行"; exit 1; }

echo "1. 移除 /etc/hosts 接管条目..."
sed -i '/^127\.0\.0\.1 llmapi\.evolventapi\.com$/d; /^# llm-api-proxy: 本机接管/d' /etc/hosts

echo "2. 停止并禁用代理服务..."
systemctl disable --now llm-api-proxy.service 2>/dev/null || true
rm -f /etc/systemd/system/llm-api-proxy.service
systemctl daemon-reload

echo "3. 验证..."
getent hosts llmapi.evolventapi.com
systemctl is-active llm-api-proxy.service 2>/dev/null || echo "服务已停止"
echo "完成。域名已恢复直连（如缓存了旧解析，最多等几十秒或重启应用即恢复）。"
