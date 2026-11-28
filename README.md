# QFNU 图书馆自动签到

曲阜师范大学图书馆座位预约的自动化工具：自动登录（CAS 滑块）、每晚预约次日座位、取消/签退当天预约、次日早上签到。在 Windows 上常驻运行即可，不用每天手动点。

> **免责声明**：本项目仅用于个人学习自动化技术。请遵守学校与图书馆的使用规定，自动化操作带来的任何后果（账号风控、预约违规、黑名单等）由使用者自行承担。仓库不含任何真实账号、密码或个人信息。

## 环境要求

- Windows 10 / 11（登录环节需要本机安装 Microsoft Edge）
- Python 3.8+
- 依赖：`pip install -r requirements.txt`

## 安装

```bat
git clone https://github.com/yulike0726/qfnu-library-auto.git
cd qfnu-library-auto
pip install -r requirements.txt
```

## 首次配置

**1. 复制配置模板**

```bat
copy config.example.json config.json
```

`config.json` 已被 `.gitignore` 忽略，只留在你本机。

**2. 编辑 `config.json`**

至少填这两项：

```json
{
  "account": "你的学号",
  "password": "你的密码"
}
```

**3. 选座位**

- `book_area`：区域编号。四层自习室 = `39`，三层 = `38`，二层 = `12`，五层 = `40`
- `book_seat_no`：座位号，例如 `"047"`
- `book_seat_id`：留空即可，程序会按座位号现查

不知道座位号在哪个区域？跑一次找座脚本，它会列出各区域并给出该座位号对应的 `area` 和 `seat_id`：

```bat
python scripts\find_seat.py 047
```

**4. 首次登录**

```bat
python -m qfnu_lib.cli login
```

会拉起一个独立的 Edge 窗口自动过滑块。成功后 token 存在 `.qfnu-state\`，之后自动复用，不用再打开的浏览器（只有 token 过期时才会重新拉 Edge）。

## 命令速查

| 命令 | 作用 |
|---|---|
| `python -m qfnu_lib.cli login` | 登录并缓存 token |
| `python -m qfnu_lib.cli seat` | 查看当前预约 |
| `python -m qfnu_lib.cli in` / `out` | 立即签到 / 签退 |
| `python -m qfnu_lib.cli book` | 预约次日座位（19:20 前会等到开放时间再发请求） |
| `python -m qfnu_lib.cli cancel` | 取消当天预约（如果已签到，自动改成签退） |
| `python -m qfnu_lib.cli run` | 等到预约生效的 08:00 再签到（单次执行，定时任务用） |
| `python -m qfnu_lib.cli daily` | **常驻守护**，按配置时间点自动执行预约/取消/签到/自查（推荐） |

通用参数：

- `--dry`：只打印将要做什么，不真正提交
- `--profile 名字`：指定账号，多账号时使用

## 每日自动化（推荐）

```bat
python -m qfnu_lib.cli daily
```

常驻运行，每 20 秒检查一次时间，到点执行：

| 时间 | 动作 |
|---|---|
| 19:15 | 提前登录 + 预先查好次日座位 id（避开 19:20 的登录高峰） |
| 19:20 | 预约次日座位，失败每 2 秒重试，最多重试 10 分钟 |
| 21:40 | 取消当天预约；已签到的直接签退，失败每 30 秒重试，最多 15 分钟（赶在 22:00 前完成） |
| 08:01 | 签到，失败每 30 秒重试，最多 22 分钟 |
| 08:25 | **自查**：确认今天真的签到成功；没签到就在 08:30 判定违规前继续补签，仍失败则写 `logs\alert.log` 并在桌面放一个 `图书馆签到失败-<日期>.txt` |

- 启动时会自动补做：已过 19:20 而明天还没约到 → 立即补约；8:00–8:25 还没签到 → 补签；8:25–8:29 启动 → 直接跑自查。
- 日志：`logs\task.log`；需要你人工处理的问题会额外写进 `logs\alert.log`。
- 以上时间点都可以在 `config.json` 里改（`book_start_at`、`book_at`、`cancel_at`、`checkin_at`、`verify_at`）。

### 开机自启（可选但建议）

daemon 需要常驻，建议用仓库自带的 watchdog 托管，掉线 45 秒内自动拉起：

```bat
echo start "" /b wscript.exe //nologo "%~dp0tools\qfnu_watch.vbs" > tools\autostart.bat
```

然后把 `tools\qfnu_watch.vbs` 的快捷方式（或上面生成的 `autostart.bat`）放进启动项
（`Win+R` 输入 `shell:startup` 打开启动文件夹，把文件拖进去）。

> watchdog 的账号列表在 `tools\watch_qfnu.ps1` 的 `$accounts` 里，用几个账号就写几项；
> 单账号只留 `main` 一项即可。

## 多账号

用 `QFNU_PROFILE` 环境变量切换账号，每个 profile 的配置、token、日志完全隔离：

| profile | 配置文件 | 状态目录 | 启动脚本 |
|---|---|---|---|
| （默认） | `config.json` | `.qfnu-state\` | `run_daily.bat` |
| `qzm` | `config.qzm.json` | `.qfnu-state\qzm\` | `run_daily2.bat` |

```bat
set QFNU_PROFILE=qzm
python -m qfnu_lib.cli login
python -m qfnu_lib.cli daily
```

每个 profile 必须用**不同的** `edge_profile` 和 `cdp_port`（例如 9222 / 9223），否则两个账号会抢同一个 Edge 用户目录：

```json
"edge_profile": "tools/edge-profile-qzm",
"cdp_port": 9223
```

加新账号：复制一份 `config.<名字>.json` 改账号和端口，再复制 `run_daily2.bat` 改成对应 profile，最后在 `tools\watch_qfnu.ps1` 的 `$accounts` 里加一行。

## 配置项

| 键 | 默认值 | 说明 |
|---|---|---|
| `account` / `password` | 空 | 学号 / 密码 |
| `book_area` | `39` | 预约区域编号（39 = 四层自习室） |
| `book_seat_no` | `"043"` | 目标座位号 |
| `book_seat_id` | 空 | 座位 id，留空按座位号现查 |
| `book_start_at` | `"19:15"` | 提前登录、预查座位的时间 |
| `book_at` | `"19:20"` | 次日预约开放时间 |
| `cancel_at` | `"21:40"` | 取消/签退时间 |
| `checkin_at` | `"08:01"` | 签到时间 |
| `verify_at` | `"08:25"` | 自查时间：确认今天签到成功，没成功就补签并报警 |
| `verify_max_minutes` | `4` | 自查发现没签到时，最多抢救多少分钟（到 08:29:30 封顶） |
| `book_window_minutes` | `10` | 预约重试窗口（分钟） |
| `book_retry_sec` | `2` | 预约重试间隔（秒） |
| `cancel_retry_sec` / `cancel_max_minutes` | `30` / `15` | 取消/签退重试间隔与窗口 |
| `checkin_retry_sec` / `checkin_max_minutes` | `30` / `22` | 签到重试间隔与窗口 |
| `job_retry_sec` / `job_max_crashes` | `30` / `40` | 任务崩溃（断网、超时）后的重排队间隔与最多重试次数 |
| `edge_exe` | Edge 默认路径 | 浏览器路径，装在别处时改这里 |
| `edge_profile` / `cdp_port` | `tools/edge-profile-clean` / `9222` | 独立浏览器用户目录与调试端口，多账号务必不同 |

## 常见问题

**登录时卡住 / 超时？**
程序会自动杀掉卡死的 Edge 进程再重试一次。如果连续失败，手动关掉所有该 profile 的 Edge 窗口，删掉 `tools\edge-profile-*` 目录后重新 `login`。

**token 多久过期？**
不确定，程序会自己判断：日常运行只用缓存的 token，失效了才拉 Edge 过滑块，不需要你干预。

**两个账号会不会互相踢下线？**
不会，只要 `edge_profile` 和 `cdp_port` 不同。仍可能偶尔看到「账号在其他设备登录」的提示，那是 token 刷新导致的，不影响使用。

**日志在哪？**
`logs\task.log`（默认账号）、`logs\task-<profile>.log`（多账号）、`logs\watchdog.log`（watchdog）。

**桌面突然出现「图书馆签到失败-xxxx-xx-xx.txt」？**
说明 08:25 的自查发现当天还没签到成功，8:30 之后会记 1 次违规。立刻去图书馆刷脸/扫码签到，或手动跑 `python -m qfnu_lib.cli in`。同时看 `logs\task.log` 里当天的报错——多数是断网或服务器超时，程序已经在 08:01–08:29 之间反复重试过了。

**断网了会怎样？**
所有请求的超时、连接失败都会当成「这次没成」继续重试，不会让守护进程崩掉：签到窗口内 30 秒一次，任务整体崩溃则每 30 秒重新排队（最多 40 次）。

**能不能只签到、不预约？**
可以，把 `config.json` 里的 `book_at` / `cancel_at` 改成一个不会触发的时间（比如 `"00:00"`），只保留 `checkin_at`。