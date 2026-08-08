# 部署指南

本项目的几种运行方式，按推荐程度排序。配置项详解见 [configuration.md](./configuration.md)。

> 📌 前置依赖:Python ≥ 3.11 · Node ≥ 20 · [`uv`](https://docs.astral.sh/uv/) · `pnpm`（`npm i -g pnpm`）

---

## 方式 A:Dev 模式(二次开发推荐)

由于刚开源近期更新频繁,推荐开发模式运行,可随时 `git pull` 同步最新代码。

```bash
git clone https://github.com/shy3130/tickflow-stock-panel.git
cd tickflow-stock-panel
cp .env.example .env       # 按需填 TICKFLOW_API_KEY(留空 = None 模式)
./dev.sh                   # Windows: .\dev.ps1
```

`dev.sh` 自动检查 / 下载依赖、释放端口、同时起前后端,Ctrl-C 一并关闭。默认:

- 后端 → <http://localhost:3018> · 前端 → <http://localhost:3011>
- 自定义端口:`BACKEND_PORT=8000 FRONTEND_PORT=5173 ./dev.sh`

### 手动分别启动(不想用 dev.sh)

```bash
# 后端
cd backend && uv sync --extra backtest   # 含回测依赖
# 老 CPU: uv sync --extra legacy-cpu
# 老 CPU + 回测: uv sync --extra legacy-cpu --extra backtest
uv run uvicorn app.main:app --reload --port 3018

# 前端
cd frontend && pnpm install && pnpm dev   # http://localhost:3011
```

---

## 方式 B:Docker(部署最省心)

```bash
cp .env.example .env
docker compose up --build
# 打开 http://localhost:3018
```

Docker 采用两阶段构建,前端 dist 拷进后端镜像,**单容器**运行,数据完全在自己手里。

> ⚠️ **stock-sdk 插件默认不打包(合规考虑)**
>
> stock-sdk 数据源本质是抓取第三方财经网站(如东方财富)的行情接口,未经对方授权,可能违反其服务条款并涉及交易所行情版权问题。**出于合规考虑,Docker 默认构建不再内置 stock-sdk 插件依赖**。
>
> - **默认行为**:`docker compose up --build` 构建出的镜像**不含** stock-sdk,插件不可用。
> - **如确需启用**(自行承担合规责任):
>   ```bash
>   docker compose build --build-arg INCLUDE_STOCKSDK=1
>   docker compose up -d
>   ```
> - 启用后镜像会额外内置 Node.js 运行时并预装 stock-sdk 依赖,插件开箱即用。
> - **建议优先使用 TickFlow 等正规授权数据源。**

更新到新版本:

```bash
git pull
docker compose up --build -d
```

### 生产 Docker Compose 部署

生产环境建议使用独立的源码目录、私有 `.env` 和私有 Compose override，避免把运行数据、认证配置或反向代理配置混入仓库。以下示例只使用通用占位符，不要把真实密码、API Key、SSH 私钥、服务器地址、域名或 Tunnel 凭据写入代码仓库或文档。

#### 目录约定

```text
<APP_DIR>/                         # Git 源码目录，例如 /opt/tickflow-stock-panel
<DATA_DIR>/                        # 运行数据目录，例如 /data/tickflow-stock-panel
<APP_DIR>/.env                     # 私有环境配置，权限 600
<APP_DIR>/docker-compose.override.yml  # 私有生产覆盖，权限 600
```

`<DATA_DIR>` 应作为 Docker 的 `/app/data` 持久化挂载。不要使用 `docker compose down -v`、`git clean -fdx`、`git reset --hard` 或删除整个源码目录的方式更新部署。

#### 私有环境配置

从模板创建 `.env`，真实值只保存在部署主机的权限受控文件或密钥管理系统中：

```bash
cp .env.example .env
chmod 600 .env
```

无实时行情需求时可以保持：

```ini
TICKFLOW_API_KEY=
```

启用 Sequoia-X 第三方数据源时，在私有 `.env` 中设置：

```ini
BACKEND_EXTRAS=sequoia
```

公网部署必须配置访问密码，但本文不记录密码本身：

```ini
AUTH_PASSWORD=<在部署主机本地填写的强密码>
```

AI 配置同样只在私有 `.env` 或应用设置页录入，不要把真实 Key 写入 Git：

```ini
AI_PROVIDER=openai_compat
AI_BASE_URL=<兼容 OpenAI API 的服务地址>
AI_API_KEY=<部署主机本地填写>
AI_MODEL=<部署主机本地填写>
```

#### 私有 Compose override

当生产环境需要让现有反向代理通过 Docker 网络访问应用时，在 `<APP_DIR>/docker-compose.override.yml` 写入以下内容。`proxy` 必须是部署主机上已经存在的外部 Docker 网络；不要在项目仓库中提交该文件：

```yaml
services:
  app:
    ports: !override
      - "127.0.0.1:3018:3018"
    environment:
      PORT: "3018"
    volumes:
      - <DATA_DIR>:/app/data
    networks:
      default:
      proxy:
        aliases:
          - tickflow-stock-panel

networks:
  proxy:
    external: true
```

启动前先检查最终 Compose 配置：

```bash
cd <APP_DIR>
docker compose config
docker compose ps
```

确认以下约束成立：

- 应用只绑定宿主机回环地址 `127.0.0.1:3018`；
- 数据卷指向 `<DATA_DIR>:/app/data`；
- `proxy` 为已有外部网络；
- `BACKEND_EXTRAS=sequoia` 被解析为构建参数；
- 启用 stock-sdk 时，构建日志/配置明确显示 `INCLUDE_STOCKSDK=1`；
- `.env` 和 override 文件权限为 `600`。

#### 构建、启动与健康检查

国际网络环境使用：

```bash
cd <APP_DIR>
docker compose build --build-arg USE_CN_MIRROR=0
docker compose up -d --remove-orphans
curl -fsS http://127.0.0.1:3018/health
```

如需在生产镜像中启用可选 `stock-sdk` 插件，必须显式传入构建参数：

```bash
cd <APP_DIR>
docker compose build \
  --build-arg USE_CN_MIRROR=0 \
  --build-arg INCLUDE_STOCKSDK=1
docker compose up -d --force-recreate --remove-orphans
```

启用后 Docker 会安装 Node.js 运行时和 `stock-sdk` 依赖。该插件通过第三方财经网站接口获取行情，可能受对方服务条款、反爬限制和行情版权约束；启用者应自行确认授权与合规性。默认只验证插件探活，不建议未经评估就切换全市场日 K、分钟或实时数据源，也不要在高频任务中反复请求上游接口。

如需禁用，重新构建时显式传入：

```bash
docker compose build \
  --build-arg USE_CN_MIRROR=0 \
  --build-arg INCLUDE_STOCKSDK=0
docker compose up -d --force-recreate --remove-orphans
```

预期健康响应至少包含：

```json
{"status":"ok"}
```

使用 Sequoia-X 时，启动日志应能看到插件注册信息；随后可在「设置 → 数据源」确认插件状态。生产镜像为 ARM64 或其他架构时，应使用目标主机架构构建，或使用已验证的多架构镜像。

#### 分支部署与更新脚本

部署脚本应接收显式分支参数，默认分支按项目约定设置。示例：

```bash
BRANCH=main sudo <DATA_DIR>/deploy.sh
```

脚本推荐执行以下顺序：

1. `git fetch --prune` 获取指定分支；
2. 使用 `git merge --ff-only` 更新源码；
3. 执行 `docker compose build`；
4. 执行 `docker compose up -d --remove-orphans`；
5. 轮询 `/health`，失败时输出容器日志并返回非零状态。

脚本不得执行清理运行数据的命令，也不得打印 `.env` 的内容。部署 Sequoia-X 的项目主分支时，确认私有 `.env` 仍保留 `BACKEND_EXTRAS=sequoia`。

#### 反向代理与 Cloudflare Tunnel

推荐访问链路为：

```text
客户端 HTTPS
  -> Cloudflare Tunnel
  -> 现有反向代理容器
  -> tickflow-stock-panel:3018
```

反向代理和 Tunnel 的具体配置属于部署主机私有配置，不写入本仓库。反向代理上游使用 Docker 网络内的：

```text
tickflow-stock-panel:3018
```

不要把应用的 3018 端口直接开放到公网。反向代理应正确转发 WebSocket 和 `X-Forwarded-For`；Cloudflare 缓存规则不要缓存 `/api/*` 和 `/health`。

#### Sequoia-X 部署后验证

```bash
# 版本与分支
git branch --show-current
git rev-parse --short HEAD

# 容器与数据卷
docker compose ps
docker inspect TickFlow_Stock_Panel

# 健康检查
curl -fsS http://127.0.0.1:3018/health
```

认证后在 API 或设置页检查：

- `sequoia_x` 插件为 `available=true`；
- `stocksdk` 插件在显式启用时为 `available=true`，并显示探活状态；
- Baostock 日 K 返回标准字段；
- AkShare 扩展数据按实际上游结果显示；
- Sequoia-X 6 个策略出现在股票日线策略池；
- 未声明的除权、分钟和实时数据仍按现有 provider 回退规则处理。

后端测试：

```bash
cd <APP_DIR>/backend
uv sync --extra dev --extra sequoia
uv run pytest tests/backtest/test_sequoia_strategies.py \
  tests/test_sequoia_provider.py tests/test_ext_private_placement.py -q
uv run ruff check app/plugins/sequoia_x \
  app/strategy/builtin/sequoia_*.py \
  tests/test_sequoia_provider.py tests/backtest/test_sequoia_strategies.py
```

#### 回滚

回滚前记录当前提交、镜像和数据目录状态。回滚只切换源码和镜像，不删除 `<DATA_DIR>`：

```bash
BRANCH=<已验证的上一版本分支或提交> sudo <DATA_DIR>/deploy.sh
```

如果发生启动失败，先查看：

```bash
docker compose logs --tail=200 app
docker compose ps
```

认证文件、策略、行情、回测和扩展数据都属于运行数据，应在回滚过程中保留并按项目兼容性要求处理。

---

## 老 CPU 兼容(avx2/fma 缺失)

如果运行时报 `avx2`/`fma` 缺失,或进程 `exit 132`,说明 CPU 不支持 AVX2 指令集(常见于老 VPS)。解决:

- **Dev 源码启动**:在根目录 `.env` 设置后运行 `./dev.sh` 或 Windows 的 `.\dev.ps1`;即使已有 `.venv`,启动器也会同步兼容内核
- **Docker**:在根目录 `.env` 设置后执行 `docker compose up --build`

```ini
BACKEND_EXTRAS=legacy-cpu          # 兼容老 CPU
BACKEND_EXTRAS=legacy-cpu backtest # 兼容老 CPU + 回测依赖
```

手动启动源码时，也可以在 `backend/` 目录直接执行 `uv sync --extra legacy-cpu`。不要设置 `POLARS_SKIP_CPU_CHECK`，它只会隐藏警告，实际执行不支持的指令时仍可能崩溃。

### 回测依赖说明

vectorbt → numba 体积较大,作为可选 extras(`uv sync --extra backtest`)。macOS / Intel 无预构建 wheel 时需 `brew install cmake` 现场编译。

---

## 更新代码(已部署用户必读)

拉取新版本只需一条命令:

```bash
git pull
```

**整个 `data/` 目录都不纳入 git** —— 行情 K线、财务、自选、回测、监控记录,乃至概念/行业扩展数据,全部是程序运行时生成/拉取的用户数据,`git pull` 物理上无法影响它们。新用户首次启动时,概念/行业两份扩展数据会自动从远程接口拉取,无需任何手动操作。

> ⚠️ **切勿使用以下命令"解决冲突"或"清理",它们会一次性删光 `data/` 下所有未被 git 跟踪的数据:**
> - `git clean -fdx`(最危险,会删掉所有 `.gitignore` 忽略的文件)
> - `git reset --hard`
> - 直接删除整个项目文件夹重新 `git clone`
>
> 若 `git pull` 报冲突,通常是本地误改了被跟踪的文件,请先 `git stash` 暂存再 pull,或单独联系作者,不要直接执行上面的命令。

---

## 访问密码设置(公网部署必读)

面板部署在公网服务器时,首次设置访问密码有限制 —— **必须从本机或内网访问**,以防公网上陌生人抢先设置密码锁死你的面板。

如果你在公网浏览器直接打开页面,会看到提示:

> 首次设置密码仅允许本机或内网访问,请通过 SSH/本地浏览器操作

有两种方式解决,任选其一。

### 方式一:环境变量预置密码(最简单,推荐)

在 `.env` 文件(或 Docker / 系统环境变量)里设置 `AUTH_PASSWORD`:

```bash
AUTH_PASSWORD=<在部署主机本地填写的强密码>
```

然后重启服务。启动时会自动:

1. 读取 `AUTH_PASSWORD`
2. 用 PBKDF2 哈希后写入 `auth.json`(`chmod 600`,只存哈希不存明文)
3. **之后这个环境变量就不再被读取** —— 是一次性的初始化

设完后即可用公网地址 + 这个密码正常登录。后续改密码请用页面 UI(`设置 → 修改密码`),不受环境变量影响。

**注意事项:**

- **密码至少 6 位**,否则会被跳过并记一条 warning 日志
- **仅在未设过密码时生效**。已设过密码后,改这里不会覆盖(避免重启时重置你在 UI 改的密码)
- `.env` 文件权限保持 `600`,**不要提交到 Git**
- 明文密码只存在于 `.env` / 环境变量中,落盘的是哈希,安全性等同 `auth.json`

**重置密码(忘密码时):** 删除或清空 `data/user_data/auth.json`,重启服务,会回到"未设密码"状态,此时 `AUTH_PASSWORD` 会重新生效。

```bash
rm data/user_data/auth.json   # 停服后执行,清空后重启
```

### 方式二:SSH 端口转发

不用改配置,在你**自己电脑**的终端执行(不是服务器上):

```bash
ssh -L 3018:127.0.0.1:3018 用户名@服务器IP
```

例如服务器是 `123.45.67.89`、用户名 `root`、面板端口 `3018`:

```bash
ssh -L 3018:127.0.0.1:3018 root@123.45.67.89
```

保持这个 SSH 连接**不要关**,然后在**自己电脑的浏览器**打开 `http://127.0.0.1:3018`。此时后端看到的客户端 IP 是 `127.0.0.1`(本机),能通过校验,正常显示设置密码界面。

**设完密码后**,SSH 连接可以断开 —— 密码已存进服务器,之后直接用公网地址 + 刚设的密码访问即可。

> 如果用 `PORT` 改过端口(比如 `PORT=8080`),两处都要替换:`ssh -L 8080:127.0.0.1:8080 root@IP`。

### 两种方式怎么选

| | 环境变量 | SSH 转发 |
|---|---|---|
| 操作 | 改一行配置 + 重启 | 一条 ssh 命令 |
| 需要改配置 | 是 | 否 |
| 适合 | Docker / 自动化部署 / 不熟 SSH | 临时设密码 / 能 SSH 到服务器 |
| 后续改密码 | UI(`设置 → 修改密码`) | 同左 |

推荐**方式一(环境变量)**,一次配置即可,Docker 部署尤其方便。

### 原理说明

- **为什么限制本机/内网?** 面板部署到公网后,任何人都能访问 URL。如果不限制,攻击者可以在你之前打开页面、设置一个密码,把你的面板锁死。
- **本机/内网如何判断?** 后端检查客户端 IP 是否属于 `127.0.0.1 / ::1 / 10.x / 192.168.x / 172.16-31.x`。
- **SSH 转发为什么有效?** `-L` 把本机端口通过 SSH 隧道转发到服务器的 `127.0.0.1`,等同于在服务器本地访问,客户端 IP 变成 `127.0.0.1`,通过校验。
- **反向代理注意:** 若面板在 Nginx 等反代之后,需正确配置 `X-Forwarded-For` 头,后端据此取真实客户端 IP。
