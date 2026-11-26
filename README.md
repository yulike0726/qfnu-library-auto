# QFNU 图书馆自动签到（修复版）

曲阜师范大学图书馆座位预约的自动签到工具。针对 2026 年新增的**登录安全验证**重写：
CAS 统一身份认证的滑块验证码 + 图书馆 H5 接口的 AES 加密报文体。

> **免责声明**：本项目仅为协议与自动化技术的学习记录（滑块验证码逆向、phpCAS 有状态换票、
> H5 AES 报文体加密等）。请遵守学校与图书馆的使用规定，自动化操作带来的任何后果
> （账号风控、预约违规、黑名单等）由使用者自行承担。仓库不含任何真实账号、密码或个人信息。

## 为什么原来的 GitHub 项目跑不起来

| 项目 | 问题 |
| --- | --- |
| `sakurasep/qfnuLibraryBook`、`w1ndys/qfnu-library-book`（2024） | 走的还是旧的明文接口 / 旧的 CAS 登录，验证码一加全挂 |
| `hunaol/qfnu_library`（2026-08） | 滑块签名算法写对了，但**缺口定位不可靠**（亮度轮廓匹配），且**换 token 时没有复用 PHP 会话**，phpCAS 直接 500 |
| `GqLx-Y/QFNULibraryBook`（2026-07） | 只处理了滑块，接口层仍是旧的 |
| `yulike0726/QFNULibraryBook` | 手工贴 CAS token，无验证码处理 |

本项目的关键修复点见下面「协议笔记」。

## 首次配置

```bat
copy config.example.json config.json
:: 然后编辑 config.json，填 account / password，按需改 book_area + book_seat_no
```

`config.json`、`config.*.json`、`.qfnu-state/`、`logs/` 都已在 `.gitignore` 里，
账号密码、token、签到日志不会被提交。

## 用法

```bat
python -m qfnu_lib.cli login     # 登录并缓存 token
python -m qfnu_lib.cli seat      # 看当前预约
python -m qfnu_lib.cli in        # 立即签到
python -m qfnu_lib.cli out       # 立即签退
python -m qfnu_lib.cli run       # 等到预约生效的 08:00 再签到（定时任务用）
python -m qfnu_lib.cli run --dry # 只算时间不签到
```

`run` 会：登录 → 找今天的 `status=2` 预约 → sleep 到 `beginTime - 5s` → 重新登录 →
每 60s 重试签到，最多 40 分钟（`config.json` 可调）。日志写到 `logs/checkin.log`。

已注册 Windows 计划任务：

```
schtasks /Query /TN QFNU-Library-Checkin
schtasks /Create /SC DAILY /ST 07:59 /TN QFNU-Library-Checkin /TR "D:\...\run.bat" /F
```

> 计划任务是 *Interactive only*：07:59 时电脑要开机并已登录该 Windows 账号，
> 否则不会执行（可以改成「不管用户是否登录都运行」并保存凭据）。

## 登录的两条路径

1. **CASTGC 快路径（默认）**：从跑着的 Edge（CDP 9222，独立 profile
   `tools\edge-profile-clean`）里读出 CAS 的 `CASTGC` cookie，直接换 ticket，全程无验证码。
2. **浏览器兜底**：CASTGC 过期时，用 CDP 驱动 Edge 打开 CAS 登录页，注入
   `qfnu_lib/cas.py::SOLVER`（canvas 上复刻 Sobel 梯度 + 拼图 alpha 掩码的归一化互相关求缺口，
   再合成 mousedown/mousemove/mouseup 拖动），滑块通过后提交表单，重新拿到 CASTGC。

   干净 profile 首次登录、或换电脑时走这条路就够，实测可全自动过滑块。

## 协议笔记（都是实测踩出来的）

### CAS（ids.qfnu.edu.cn）

- 本账号 `checkNeedCaptcha.htl?username=...` 返回 `{"isNeed":true}`，登录必须过滑块。
- 滑块接口：`GET /authserver/common/openSliderCaptcha.htl` → `{smallImage, bigImage, tagWidth, yHeight}`。
  `smallImage` 是 PNG，**PNG 的 IEND 之后还追加了 16 个 ASCII 字节**，这 16 字节就是签名密钥（`safeSecure.value`）。
- 校验：`POST /authserver/common/verifySliderCaptcha.htl`，
  `sign = encryptPassword(JSON.stringify({canvasLength, moveLength, tracks}), secret)`。
  - `canvasLength` 恒为 280（`#sliderDiv` 宽度），`moveLength` 是鼠标总位移，
    `tracks` 是每 ≥20ms 一个 `{a:累计dx, b:dy, c:距上次毫秒}`，首点 `{0,0,0}`。
  - 签名：AES-CBC/PKCS7，key = secret（去首尾空白），iv = 16 位随机可打印字符，
    明文前加 64 位随机字符，输出 base64。
- 注意：**纯协议直连 verify 会被拒**（`{"errorCode":0,"errorMsg":"error"}`），
  即使缺口定位完全正确。服务端绑定了浏览器会话/时序，所以本项目用真浏览器过滑块，
  不用 Python 伪造请求。

### 换票（libyy 的 phpCAS 有状态，必须三步）

```
1. GET  http://libyy.qfnu.edu.cn/api/cas/cas                  -> 建 PHP session
2. GET  http://libyy.qfnu.edu.cn/api/cas/cas?ticket=ST-...    -> 会话内标记已认证
3. GET  http://libyy.qfnu.edu.cn/api/cas/cas                  -> 302 #/cas/?cas=<32位hex>
```

少了第 1 步直接带 ticket 请求，就会拿到
`<h1>CAS Authentication failed!</h1> ... phpCAS 1.5.0 using server http://ids.qfnu.edu.cn:80/authserver/`。
再用 `POST /api/cas/user {"cas": "<hex>"}` 换 JWT（`member.token`）。

### 图书馆 H5 接口

- 请求头 `Authorization: bearer<token>`（**没有空格**）。
- `encryptRequest` 名单里的接口body要包成 `{"aesjson": base64}`：
  AES-CBC/PKCS7，**key = YYYYMMDD + reverse(YYYYMMDD)**（如 `2026111441161120`），
  **iv = `ZZWBKJ_ZHIHUAWEI`**（固定常量，别误用 key 当 iv）。
- 签到：`POST /api/Seat/touch_qr_books {"method":"checkin"}`（加密）；
  查询：`POST /api/Member/seat`（明文）。
- 预约生效前签到返回 `{"code":0,"msg":"对不起，您的预约未生效"}`，这是正常的，等 08:00 再签。

### 环境坑

- 浏览器（两个 profile 都一样）访问 `http://libyy.qfnu.edu.cn` 会被
  `net::ERR_BLOCKED_BY_CLIENT` 拦掉，`https://libyy` 443 未开放，所以**签到只能走 Python**。
- CDP 取 cookie 要连 **page target** 的 WebSocket（`/json/list` 里 `type=page`），
  连 browser 级 WS 再 `Network.getAllCookies` 返回 0 条。

## 目录

```
qfnu_lib/
  settings.py   配置加载（config.json，密码缺失时回落 .qfnu-state/config.json）
  cas.py        CASTGC/ticket/phpCAS 换票 + CDP 浏览器滑块兜底
  api.py        加密 API 客户端（my_seat / checkin / checkout）
  cli.py        命令行入口
test_browser_login.py   在 9223 端口的临时 profile 上验证滑块兜底
run.bat                 计划任务入口（签到）
run_daily.bat           每日调度入口（预约/取消/签到）
```

## 预约 / 取消（2026-11 逆向）

四层自习室 = `build_id`/`area` **39**，座位号 043 = `seat_id` **7330**（042=7329、048=7335，
连续编号；也可用 `seat_list` 按 `no` 现查，config 里 `book_seat_id` 留空即现查）。

```
# 1) 可预约日期 + 时段（build_id 必须是真实楼栋 id，否则 500 "Undefined index: id"）
POST /api/Seat/date  {"build_id":39}
#  -> data:[{"day":"2026-11-15","times":[{"id":"1837764","status":1,"start":"08:00","end":"22:00"}]}]

# 2) 座位列表（可选，用于把 043 换成 seat_id）
POST /api/Seat/seat  {"area":39,"segment":"1837764","day":"2026-11-15",
                      "startTime":"08:00","endTime":"22:00"}

# 3) 预约（加密接口）——open 时间 19:20，之前返回 "开放预约时间19:20"
POST /api/Seat/confirm  {"seat_id":7330,"segment":"1837764"}      // {"aesjson": ...}
#  成功返回 code=1，msg 是"预约提醒"（8:30 前签到等），**没有第二步确认**

# 4) 取消（明文）——id 是 /api/Member/seat 里那条预约的 booking id（不是 space/seat id）
POST /api/Space/cancel  {"id":1234567}
#  已经签到/已开始时返回 "禁止取消"，此时应改走签退 touch_qr_books {"method":"checkout"}
```

- `GET/POST /api/index/config` 返回加密的整站配置（`web.seatcancel=-30`、`config.new=19:20` 等）。
- H5 的 `index.1703080339151.js` 里 `/api/Seat/tree`、`/reserve/index/*` 在本服务端并不存在，
  别照着 H5 的 `fetchSeatTree` 走；日期只能靠 `/api/Seat/date {build_id}`。

## 每日自动化

`python -m qfnu_lib.cli daily` 常驻，按 config 里的时间点执行（20 秒轮询一次）：

| 时间 | 动作 | 实现 |
|---|---|---|
| 19:15 | 提前登录 + 预先查好座位 id | `cmd_book` 前半段：趁人少登录（缓存 token→CASTGC→Edge），把 segment/seat_id 算好 |
| 19:20 | 预约次日座位（config 的 `book_area`/`book_seat_no`） | 只在整点发 `confirm`，每 2s 重试，最多 10 分钟 |
| 21:40 | 取消当天预约 / 签退 | `cmd_cancel`：`status=2` 走 `/api/Space/cancel`；`status=3`（使用中/已签到）直接签退，签名失败每 30s 重试，最多 15 分钟（保住 22:00 前完成签退，避免记违规） |
| 08:01 | 签到 | `cmd_checkin_window`，每 30s 重试，最多 25 分钟 |

- 启动时会 `_catchup()`：若已过 19:20 且明天没预约就立即补约；若在 8:00–8:25 且今天没签到就补签。
- 开机自启：`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\qfnu-library-daily.bat`
  调用 `run_daily.bat`（沙箱里 `schtasks /Create` 被拒绝，Access is denied，所以走启动项）。

## 多账号（profile）

`QFNU_PROFILE` 环境变量切换账号，两套配置和状态完全隔离：

| profile | 账号 | 配置文件 | 状态目录 | 座位 | 启动脚本 |
|---|---|---|---|---|---|
| （空） | 账号 A 的学号 | `config.json` | `.qfnu-state\` | 以 `config.json` 的 `book_seat_no` 为准 | `run_daily.bat` |
| `qzm` | 账号 B 的学号 | `config.qzm.json` | `.qfnu-state\qzm\` | 以 `config.qzm.json` 的 `book_seat_no` 为准 | `run_daily2.bat` |

```bat
set QFNU_PROFILE=qzm
python -m qfnu_lib.cli login      :: 首次：跑一次浏览器滑块，token 存 .qfnu-state\qzm\lib_session.json
python -m qfnu_lib.cli daily
```

每个 profile 用独立的 `edge_profile` 和 `cdp_port`（例如 9222 / `tools\edge-profile-clean`，
9223 / `tools\edge-profile-qzm`），否则两个账号会抢同一个 Edge 用户目录。
加第三个账号：照抄一份 `config.<name>.json`、复制 `run_daily2.bat` 改成对应 profile，
再在启动项里加一行 `start "" /min run_dailyN.bat`。
