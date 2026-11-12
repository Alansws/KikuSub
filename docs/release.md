# 发版规范（四步）

> 发一次版 = 走完四步，缺一步就停。**本文是发版的唯一依据**；能自动化的部分已经变成硬失败
> （本地 `tools/release/preflight.sh`、CI 的 `release-tag` job），剩下的必须人来判断。
>
> 相关：[AGENTS.md](../AGENTS.md) §5 改动纪律、[engineering-practice.md](contracts/engineering-practice.md)
> §⑤ 发版护栏、[tools/pack/](../tools/pack/) 装配脚本。

---

## 0. 版本号与分支（先对齐，再动手）

**分支模型**（2026-11-13 定）：

| 分支 | 角色 | 规则 |
| --- | --- | --- |
| `main` | **主线** | 只接收"已测试"的改动；**只有它能打发版 tag** |
| `app/macos` | 开发分支 | 日常开发都在这里；`pytest` / CI 绿了才合入 `main` |

**版本号唯一来源**是 `desktop/package.json` 的 `version`：

- `tools/pack/build_app.sh` 和 `build_dmg.sh` 都从它读，不许在别处写死；
- `package-lock.json` 的根版本必须同步（`tests/test_pack_version.py` 看守）；
- tag 名 = `v<version>`，例如 `0.3.0` → `v0.3.0`。

**semver 口径**：修 bug 动补丁位；新功能动次版本位；破坏用户数据（`presets.json` / 草稿格式）
或大改交互才动主版本位。

**一次发版的顺序固定为**：

```
app/macos 上改完 → 测试绿 → bump 版本号 → 合入 main → 在 main 上打 tag
```

顺序反了会出两类事故：tag 打在开发分支上（CI 会红，见 §7）；或者 bump 落在合并之后
（`main` 上的提交与 tag 对不上，回滚时找不到"发的是哪一版"）。

---

## ① 合入审查：`app/macos` → `main`

```bash
# 1) 开发分支上，本地全量必须绿（与 AGENTS.md §5 的验证顺序一致）
pytest -q
python -m core.smoke
cd desktop && npm run build && npm run test:main && cd ..

# 2) 推送并确认 CI 绿
git push origin app/macos          # CI: lint + pytest + smoke 必须绿

# 3) bump 版本号（在开发分支上，作为一个独立提交）
#    编辑 desktop/package.json 的 version + desktop/package-lock.json 的根版本
git commit -am "chore(release): 0.3.0"

# 4) 合入主线
git checkout main
git merge --no-ff app/macos        # --no-ff 保留"这批改动一起合入"的合并点，便于整批回滚
git push origin main
```

**审查口径**：合入前只看四件事——业务是否真跑通（有无端到端/有无没意义的测试）、实现是否优雅
（冗余代码 / 自造轮子）、有没有复用已有基建、有没有踩 `AGENTS.md` §4 的红线。发现问题就回
`app/macos` 改，**不要在 `main` 上直接改**。

> 为什么用 `--no-ff`：单条 tag 之外，还需要一个"这一批发版包含哪些提交"的边界。
> 线性快进也能发版，但回滚时要靠 tag diff 反推范围。

---

## ② 本地实测（不许跳过）

```bash
# 1) 发版前置检查：版本号 / tag 是否已存在 / sidecar 新鲜度 / 工作区干净 / 快速测试
bash tools/release/preflight.sh --with-tests

# 2) 重打 sidecar + 构建渲染层 + 装配 .app（第一次会跑 3–5 分钟）
bash tools/pack/rebuild.sh --no-open

# 3) 打开装配好的 app，按下面清单手点
open build/pack/KikuSub.app
```

**必须手点的主链路**（自动化覆盖不到的那部分）：

1. 导入一个视频 → 能看到波形与视频画面；
2. 转写用最短样本跑一次（或用 `KIKUSUB_DEV_SEED` 直接造出核对台状态，见 `desktop/README.md`）；
3. 核对台：单击跳转、拖动框选（超过 4px 才建选区）、缩放、改一句、⌘Z 一次退回、暂存；
4. 导出：字幕（原文/译文/双语）各一次 + 成片导出一次；
5. 退出：走退出清理，不弹错误，进程真的退干净。

**失败即停**。发版前一天"先发再修"的记录，对应的都是把用户当测试机。

---

## ③ 云端打包与分发

```bash
bash tools/pack/build_dmg.sh
# 产出 build/pack/dist/KikuSub-<version>-<arch>.dmg（卷图标已内嵌）
```

在 GitHub 上：

1. 新建 Release，tag 选 `v<version>`（**必须在 `main` 上**，CI 会校验）；
2. 上传 `.dmg`；
3. 正文按 §5 的模板写 Release notes；
4. 确认不是 "pre-release"（除非本轮是测试版）。

> 本项目 **ad-hoc 签名、未经公证、没有 autoUpdater**。用户从浏览器下载后会被 Gatekeeper 拦一次，
> 需要右键「打开」或 `xattr -dr com.apple.quarantine`。这条要写进 Release notes 的"安装"一节，
> 否则第一次装的人会以为软件坏了。

---

## ④ 发布日志

- Release notes 写进 GitHub Release（唯一对外日志，不做本地 CHANGELOG——两处写必然漂移）；
- 用户可见行为变了 → 同步 `README.md` / `README_EN.md`；
- 有已知问题 → 写进 notes 的"已知问题"，并开一个 issue 跟进。

---

## ⑤ Release notes 模板

```markdown
## KikuSub <version>

<一句话说这一版解决什么，不要罗列提交>

### 新增
- <做了什么、在哪个界面能看到>

### 改进
- <原来什么表现，现在什么表现。有数字就写数字>

### 修复
- <用户报障的现象 → 原因 → 现在怎么处理>

### 安装
下载 `KikuSub-<version>-<arch>.dmg`，拖进「应用程序」。首次打开需右键「打开」
（应用未公证，这是 Gatekeeper 的预期行为）。

### 已知问题
- <没有就写"无">
```

写之前先 `git log --oneline v<上一个版本>..HEAD`，再对照[项目定位](../AGENTS.md)筛出**用户能感知的**
变化；内部重构（去重、测试、文档）不进 notes 的"新增/改进"。

---

## ⑥ 发版后验证与回滚

**发版后 24 小时看两件事**：

1. `desktop/main/launchguard.cjs` 的启动失败计数——用户本机 `preferences.json` 里的
   `launchFailures` 连续 ≥2 就会进安全模式（只弹一个对话框给下载页）。收到的反馈里出现
   "一打开就退"，优先查这个；
2. 新版本在 Releases 页的下载量与 issue 里有没有集中同类问题。

**回滚口径**（本项目没有云端更新配置，所以做不到"秒级切回"）：

| 情况 | 处理 |
| --- | --- |
| 小问题、不影响使用 | 不急发版，修好进下一个版本 |
| 影响核心链路（打开即崩 / 转写不出字幕） | 立刻发补丁版：`main` 上修 → bump 补丁位 → 走完四步 → 把新 Release 置顶，旧 Release 正文加一行"建议升级到 x.y.z" |
| 补丁版也修不好 | 把出问题的 Release 标记为 **pre-release**（不让它出现在默认列表），正文写明回退版本与手动安装方法 |

**绝不做**：

- **改已发布 tag 的指向**——用户手上的 DMG 与仓库里的 tag 会对不上，且缓存/CDN 还可能是旧包；
- **同版本号重发**——版本显示、`About` 面板与用户反馈里的版本号全部失效；
- 静默替换 Release 附件——已经下载的人不会知道。

> 安全模式是最后一道兜底：`launchguard` 连续两次启动失败后会跳过业务模块与旧工程，
> 只让用户点「检查更新 / 去下载」。所以**"补丁版必须能在 Releases 页面被老用户找到"**
> 比"立刻发版"更重要。

---

## ⑦ 自动化边界（哪些已经不用人记）

| 检查项 | 谁做 | 失败表现 |
| --- | --- | --- |
| tag 名 == `desktop/package.json` 版本 | CI `release-tag` job | 红，Release 卡住 |
| tag 提交在 `main` 上 | CI `release-tag` job | 红（在 `app/macos` 上打 tag 会被拦） |
| `package.json` ↔ `package-lock.json` 版本一致 | `tests/test_pack_version.py` | pytest 红 |
| `build_app.sh` 不写死版本号 | `tests/test_pack_version.py` | pytest 红 |
| 版本号没改就发 | `tools/release/preflight.sh`（tag 已存在） | 脚本退出码 1 |
| sidecar 比 `core/` `server/` 源码旧 | `build_app.sh` + `rebuild.sh` + preflight | 直接退出（有意） |
| 渲染层没构建就装配 | `build_app.sh`（缺 `renderer/dist` 退出） | 直接退出 |
| 图标换了没重生成 | `build_app.sh` 每次都从 `docs/app-icon.png` 重渲染 | 不会漏 |
| 工作区有未提交改动就发版 | `tools/release/preflight.sh` | 退出码 1 |

**本地钩子（可选，一次配置）**：把发版闸门挂到 `git push` 上——

```bash
git config core.hooksPath tools/git-hooks
```

钩子只拦 `v*` tag 的推送（普通推送放行），被拦时提示先跑 `tools/release/preflight.sh`。
CI 的 `release-tag` job 才是硬约束；钩子只是让本地早点发现。

---

## ⑧ 常见翻车

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| 新界面点了报 404 / Method Not Allowed | 只重打了 app，没重打 sidecar | `bash tools/pack/rebuild.sh`（第一次 3–5 分钟） |
| `About` 里版本与 tag 不一致 | 改了 tag 没改 `package.json`，或反过来 | 先改 `package.json`，再打 tag；CI 会拦 |
| DMG 在访达里是白色通用磁盘 | 卷图标没写进去 | `build_dmg.sh` 会自动处理；若手动打包需 `.VolumeIcon.icns` + `SetFile -a C` |
| 下载后打不开 | Gatekeeper（未公证） | Release notes 写清右键「打开」 |
| 用户升级后 AI Key 失效 | 千万别改成 `safeStorage`（见 `docs/contracts/ai-proposal.md`） | 保持 `aikey.cjs` 方案 |
