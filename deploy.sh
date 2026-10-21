#!/usr/bin/env bash
# One-command deployment: prepare dirs + NapCat reverse-WS config, then
# build/start both containers. QQ login (QR scan) is the only manual step.
set -euo pipefail

cd "$(dirname "$0")"

say() { printf "\033[1;36m%s\033[0m\n" "$*"; }
err() { printf "\033[1;31m%s\033[0m\n" "$*" >&2; }

command -v docker >/dev/null 2>&1 || { err "未安装 Docker，请先安装 Docker Engine"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "未安装 Docker Compose v2（docker compose）"; exit 1; }

if [ ! -f .env ]; then
    cp .env.example .env
    err "已生成 .env。请填写 CTF_BASE_URL / CTF_RACE_ID / CTF_VIEWER_KEY / CTF_GROUP_ID /"
    err "ONEBOT_ACCESS_TOKEN / NAPCAT_TOKEN，然后重新执行 ./deploy.sh"
    exit 1
fi

get_env() {
    local key="$1"
    grep -E "^${key}=" .env | tail -n 1 | cut -d= -f2- \
        | sed -e 's/\r$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

missing=0
for key in CTF_BASE_URL CTF_RACE_ID CTF_VIEWER_KEY CTF_GROUP_ID ONEBOT_ACCESS_TOKEN NAPCAT_TOKEN; do
    value="$(get_env "$key" || true)"
    case "$value" in
        ""|*"<"*|"change-me"*)
            err "请在 .env 中填写 $key"
            missing=1
            ;;
    esac
done
[ "$missing" -eq 0 ] || exit 1

mkdir -p data/bot data/napcat/config data/napcat/qq

NAPCAT_CONFIG="data/napcat/config/onebot11.json"
if [ ! -f "$NAPCAT_CONFIG" ]; then
    token="$(get_env ONEBOT_ACCESS_TOKEN)"
    case "$token" in
        *'"'*|*\\*)
            err "ONEBOT_ACCESS_TOKEN 不能包含双引号或反斜杠"
            exit 1
            ;;
    esac
    cat > "$NAPCAT_CONFIG" <<EOF
{
  "network": {
    "httpServers": [],
    "httpSseServers": [],
    "httpClients": [],
    "websocketServers": [],
    "websocketClients": [
      {
        "enable": true,
        "name": "rws",
        "url": "ws://bot:8080/onebot/v11/ws",
        "reportSelfMessage": false,
        "messagePostFormat": "array",
        "token": "${token}",
        "debug": false,
        "heartInterval": 30000,
        "reconnectInterval": 30000
      }
    ],
    "plugins": []
  },
  "musicSignUrl": "",
  "enableLocalFile2Url": false,
  "parseMultMsg": false
}
EOF
    say "已生成 NapCat 反向 WS 配置：$NAPCAT_CONFIG"
else
    say "保留已有 NapCat 配置：$NAPCAT_CONFIG（如需重建请先删除）"
fi

if compgen -G 'data/napcat/config/onebot11_*.json' >/dev/null; then
    python3 scripts/sync_napcat_config.py
fi

if docker image inspect mlikiowa/napcat-docker:latest >/dev/null 2>&1; then
    say "使用本地 NapCat 镜像"
else
    say "拉取 NapCat 镜像..."
    docker compose pull napcat
fi

say "构建并启动容器..."
if ! docker compose up -d --build; then
    if ! docker image inspect ctf-blood-bot:latest >/dev/null 2>&1; then
        err "构建失败，且本地没有 bot 镜像；请检查 Docker Hub 网络后重试"
        exit 1
    fi
    err "构建失败，改用本地已有镜像启动；本次代码修改可能尚未包含在镜像中"
    docker compose up -d --no-build --pull never
fi

say "当前状态："
docker compose ps

cat <<'EOF'

============================================================
下一步（只需做一次）：
1. 打开 NapCat WebUI 并扫码登录机器人 QQ：
     http://127.0.0.1:6099/webui
   如果部署在远程服务器，请先建 SSH 隧道：
     ssh -L 6099:127.0.0.1:6099 用户名@服务器地址
2. 登录成功后，NapCat 会自动通过反向 WS 连到 bot。
3. 在目标 QQ 群发送： /ctf status
   能收到状态卡片即部署成功。

常用命令：
  docker compose logs -f bot napcat   # 看日志
  docker compose up -d --no-build     # 修改 .env 后重新创建容器
  docker compose restart bot          # 只重启现有容器
  docker compose down                 # 停止（保留 data/）
============================================================
EOF
