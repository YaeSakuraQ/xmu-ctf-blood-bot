# XMU CTF Blood Bot

把 CTF 解题赛的 **一血 / 二血 / 三血** 实时播报到 QQ 群。

基于 [GZCTF-BOT-QQ](https://github.com/MoRan23/GZCTF-BOT-QQ) 的 NapCat + NoneBot2 部署骨架二次开发：
原 GZCTF 插件保留在 `legacy/`（不加载），新增 `ctf_blood` 插件对接实训平台的**公开大屏榜单接口**。

> 机器人只用只读 GET，不登录后台、不提交 flag、不写平台数据。

---

## 特性

- **实时**：默认 2 秒轮询，端到端延迟约 2–3 秒。
- **判血准确**：直接用平台榜单里的解题顺序 `rank=1/2/3`，不是猜测。
- **精确时间/得分**：按需拉取单队解题时间线，消息里带解题时间和含血奖得分。
- **幂等**：SQLite 记录 `(赛事, 题目, 血位)`，重启不重发。
- **可补报**：停机/断网期间漏掉的血，恢复后自动补报（带“补报”标记）。
- **抗异常**：题目顺序变化自动重建基线；赛事重置自动清状态；发送失败指数退避。
- **无管理员凭据**：机器人只需要 `viewer_key`，不保存后台账号密码。
- **一键部署**：`./deploy.sh` 生成配置、构建镜像、启动 NapCat + bot。

---

## 架构

```text
实训平台 10.x
   │  GET /api/ct/public/jeopardy_race/race/{id}/rank/   (2s)
   ▼
Collector ──► Detector ──► SQLite（幂等/补发）
                  │
                  ▼
             NoneBot2 ──► NapCat（OneBot 11）──► QQ 群
```

- 榜单接口返回每题的解题顺序：`checker_score[i].rank` = 1/2/3。
- 单队接口 `/rank/{team_id}/` 返回 `create_time` 和 `score`。
- 机器人只需要 `viewer_key`，不需要登录。

---

## 一键部署

### 前置条件

1. 一台 Linux 机器（2C2G 足够），能访问：
   - 实训平台（HTTP 80）；
   - 腾讯 QQ 服务器（出站 443）。
2. 安装 Docker 与 Docker Compose v2。
3. 一个专用 QQ 小号（建议提前养号，不要用主号）。
4. 目标 QQ 群，机器人账号已入群且允许发言。

### 步骤

```bash
git clone <this-repo> ctf-blood-bot
cd ctf-blood-bot

cp .env.example .env
vim .env          # 至少填 6 项：平台地址、赛事 ID、viewer_key、群号、两个 token

./deploy.sh
```

`deploy.sh` 会：

1. 检查 `.env` 是否填全；
2. 生成 NapCat 反向 WS 配置（token 与 bot 一致）；
3. 拉取 NapCat 镜像；
4. `docker compose up -d --build`；
5. 打印 WebUI 地址和下一步。

### 登录机器人 QQ（只需一次）

```bash
# 本机部署：直接打开
http://127.0.0.1:6099/webui

# 远程服务器：先建 SSH 隧道
ssh -L 6099:127.0.0.1:6099 用户名@服务器地址
# 然后本地打开 http://127.0.0.1:6099/webui
```

输入 `.env` 里的 `NAPCAT_TOKEN`，用手机 QQ 扫码登录机器人小号。
登录成功后 NapCat 会自动通过反向 WS 连到 bot。

### 验证

在目标群里发：

```text
/ctf status
```

能收到状态卡片即部署成功。

---

## 配置

所有配置在 `.env`：

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `CTF_BASE_URL` | ✅ | — | 平台地址，如 `http://10.0.0.10`，不要结尾斜杠 |
| `CTF_RACE_ID` | ✅ | — | 赛事 ID（后台赛事列表/大屏链接里） |
| `CTF_VIEWER_KEY` | ✅ | — | 大屏 `viewer_key`，32 位十六进制 |
| `CTF_GROUP_ID` | ✅ | — | 播报目标 QQ 群号 |
| `CTF_POLL_INTERVAL` | | `2` | 轮询间隔（秒） |
| `CTF_SEND_INTERVAL` | | `1` | 两条消息最小间隔（秒） |
| `CTF_CATCHUP_MODE` | | `announce` | 首轮发现已有血：`announce` 补报 / `silent` 静默基线 |
| `CTF_BLOOD_LEVELS` | | `1,2,3` | 播报哪些血位 |
| `CTF_DRY_RUN` | | `false` | `true` 只打印不发送 |
| `CTF_DB_PATH` | | `/app/data/ctf_blood.sqlite3` | 容器内数据库路径 |
| `CTF_MAX_SEND_ATTEMPTS` | | `5` | 发送失败重试上限 |
| `CTF_SEND_ADMIN_ERRORS` | | `true` | 发送失败私聊管理员 |
| `ONEBOT_ACCESS_TOKEN` | ✅ | — | bot 与 NapCat 的 WS token，随机串 |
| `NAPCAT_TOKEN` | ✅ | — | NapCat WebUI 登录 token，随机串 |
| `SUPERUSERS` | | `["123456789"]` | 机器人管理员 QQ，JSON 列表 |
| `COMMAND_START` | | `["/"]` | 命令前缀 |
| `PORT` | | `8080` | bot 内部端口（不对外发布） |

### `viewer_key` 从哪来

后台「比赛管理 → 赛事 → 大屏」链接形如：

```text
http://<platform>/page/ct/public/ctf/screen/{race_id}/{viewer_key}
```

最后一段就是。它是赛事的只读凭据，**不要提交到 git、不要发群**。

### 首轮补报

- 赛前启动：榜单是 0 血，不会补报，开赛后正常播。
- 比赛中途重启且数据库还在：只补数据库里没有的，不会重复。
- 数据库丢了 + `announce`：会把当前所有血按 1 条/秒补发（可能 20+ 条）。
  不想刷屏就设 `CTF_CATCHUP_MODE=silent`，它会把已有血静默标记为已发。

---

## 命令

| 命令 | 权限 | 说明 |
|---|---|---|
| `/ctf status` | 群/私聊 | 运行状态、已发/待发/失败数、最近轮询、Bot 连接 |
| `/ctf rank [N]` | 群/私聊 | 实时前 N 名（默认 10） |
| `/ctf blood [关键词]` | 群/私聊 | 当前血况，可按题目/方向过滤 |
| `/ctf test` | 管理员 | 往群里发一条测试血报 |
| `/ctf reload` | 管理员 | 重载 `.env`（换 key/群号后不用重启容器） |
| `/ctf help` | 群/私聊 | 帮助 |

> 群聊里只响应 `CTF_GROUP_ID` 对应的群；私聊不受限。

---

## 工作原理

### 判血

平台榜单里每道题有一个 `checker_score[i].rank`：

- `1` = 一血，`2` = 二血，`3` = 三血；
- `0` = 未解出；
- 只在 `reward_mode=1` 时有意义（平台启用一/二/三血加成）。

机器人每轮拉全量榜单，找出 `rank ∈ {1,2,3}` 且未播报过的 `(题目, 血位, 队伍)`。
唯一键是 `(race_id, challenge_id, blood)`，所以同一血位只会发一次。

### 精确时间/得分

命中新血后，按需请求：

```text
GET /api/ct/public/jeopardy_race/race/{race_id}/rank/{team_id}/?viewer_key=...
```

取该队这条解题记录的 `create_time` 和 `score`。请求失败就退回检测时间，消息里标“时间未知”。

### 自愈

- **重启**：SQLite 里的已发记录还在，不会重发；未发的 pending 继续发。
- **断网**：恢复后下一轮全量比对，漏掉的血会补上。
- **题目顺序变化**：用 `checkpoint_id` 序列做指纹，变化时跳过一轮重建基线，避免错位。
- **赛事重置**：总分/解题数连续两轮下降超过 50%，清空该赛事播报状态并重新基线。

### 限流

- 轮询 2s，发送 1 条/秒（可配）。
- 发送失败指数退避：2s、4s、8s… 最多 5 次；仍失败则标记 failed 并私聊管理员。
- 绝不 `@全体`。

---

## 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

pytest -q
```

不接 QQ，直接跑核心逻辑：

```bash
export CTF_BASE_URL=http://<platform>
export CTF_RACE_ID=<race_id>
export CTF_VIEWER_KEY=<key>
export CTF_GROUP_ID=1
export CTF_DB_PATH=/tmp/ctf_blood.sqlite3
export CTF_CATCHUP_MODE=announce

# 只读打印当前血况
python -m ctfblood.cli probe

# 跑一轮检测 + 打印（dry-run）
python -m ctfblood.cli once
```

只读探针（无第三方依赖）：

```bash
python scripts/probe_ctf_rank.py --base http://<platform> --race <race_id> --viewer-key <key> --details
```

---

## 目录

```text
bot.py                     NoneBot 入口
ctfblood/                  核心：API、判血、SQLite、消息、CLI
plugins/ctf_blood/         NoneBot 插件：调度、命令、OneBot 发送
legacy/gzctf_bot_qq/       原 GZCTF 插件（不加载，仅参考）
tests/                     单元测试
docs/                      技术方案/调研
scripts/probe_ctf_rank.py  只读探针
Dockerfile
docker-compose.yml         bot + NapCat
deploy.sh                  一键部署
.env.example
```

---

## 常见问题

**Q: 群里没反应，`/ctf status` 也不回？**
A: 看 `docker compose logs -f bot napcat`。常见原因：NapCat 没登录、WS token 不一致、机器人不在群/被禁言、`CTF_GROUP_ID` 不对。

**Q: 一直提示“登录凭证失效/无操作权限”？**
A: `viewer_key` 不对或已轮换。从后台大屏链接重新复制，改 `.env` 后 `/ctf reload` 或 `docker compose restart bot`。

**Q: 有解题但没播报？**
A: 确认赛事 `reward_mode=1`；`/ctf status` 看 `reward_mode` 告警。`reward_mode=0` 时平台不记录血序，机器人不会误报。

**Q: 补报刷屏？**
A: 设 `CTF_CATCHUP_MODE=silent` 后重启；或等它按 1 条/秒发完。

**Q: 机器人被风控/冻结？**
A: 用专用小号、固定出口 IP、低频发送、不要 @全体；准备备用号。协议端方案有账号风险，这是已知代价。

**Q: 换赛事/换 key？**
A: 改 `.env` → `/ctf reload`（管理员）或 `docker compose restart bot`。

---

## 安全

- `.env` 含 `viewer_key` 和两个 token，已在 `.gitignore`，不要提交。
- 机器人主机不保存后台管理员密码。
- 只用公开只读接口，不调用任何写接口。
- 消息用 OneBot **text 段**发送，队名里的 `[CQ:...]` 不会被当成 CQ 码执行。
- 日志会把 `viewer_key` 替换成 `***`；httpx 的 URL 日志已降级。
- NapCat WebUI 默认只绑 `127.0.0.1`，远程用 SSH 隧道。

---

## License / 致谢

本项目基于 [GZCTF-BOT-QQ](https://github.com/MoRan23/GZCTF-BOT-QQ)（AGPL-3.0）二次开发，
沿用其 NapCat + NoneBot2 部署骨架；原插件保留在 `legacy/` 但运行时不加载。

本项目同样采用 **AGPL-3.0**，详见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

参考：

- [NapCat](https://github.com/NapNeko/NapCatQQ) / [NapCat-Docker](https://github.com/NapNeko/NapCat-Docker)
- [NoneBot2](https://github.com/nonebot/nonebot2)
- [GZCTF-BOT-QQ](https://github.com/MoRan23/GZCTF-BOT-QQ)
