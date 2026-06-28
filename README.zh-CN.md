<div align="center">

# ccclean

**用于 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 会话的精准上下文清理工具。**
从对话中裁剪掉最早的消息，释放上下文窗口——并附带一个确认步骤，以及可选的被删除内容摘要。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
![Platform: macOS | Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)

[English](README.md) · [Русский](README.ru.md) · **中文** · [Español](README.es.md) · [Deutsch](README.de.md)

</div>

---

它直接作用于 `~/.claude/projects/` 中的 `.jsonl` 会话文件。

## 目录

- [为什么选择 ccclean](#为什么选择-ccclean)
- [功能特性](#功能特性)
- [安装](#安装)
  - [API 密钥](#api-密钥)
- [使用方法](#使用方法)
- [自动清理 (钩子 + `ccclaude`)](#自动清理-钩子--ccclaude)
  - [主动模式 (`clean_at`)](#主动模式-clean_at)
  - [自动续接 (`resume_prompt`)](#自动续接-resume_prompt)
  - [钩子安全性](#钩子安全性)
- [工作原理](#工作原理)
- [面向 AI 智能体](#面向-ai-智能体)
- [注意事项](#注意事项)
- [许可证](#许可证)

---

## 为什么选择 ccclean

长时间的 Claude Code 会话会填满上下文窗口，工作也随之变得吃力：模型触及上限，
auto-compact（自动压缩）在不合时宜的时刻启动，把所有内容不加区分地一并压缩。
`ccclean` 则把**精确的控制权**交给你：由你决定释放多少 token、究竟丢弃对话中
哪一段较早的内容——而且会先给你看一段简短的摘要。对话当前（较新）的部分则原封不动。

与内置的 `/compact`（它会把*整段*对话压缩成一段摘要）不同，`ccclean` 只是
**截掉活动分支最早的开头部分**，并原样保留最近的消息。

---

## 功能特性

- ✂️ **精确裁剪**——你指定一个数量（`10k`、`50k`、`1.5m`），工具会从头开始删除
  旧消息，从而释放**至少**所请求的数量。
- 🔢 **如实的 token 计数**——默认通过官方的 Anthropic `count_tokens` API（精确），
  或借助 `tiktoken` 离线计算（`--fast`）。它会把文本、`thinking`、工具调用以及
  **图像**都计算在内。
- 📋 **被删除内容的摘要（可选）**——加上 `--summary` 参数后，在删除任何内容之前，
  它会（通过 DeepSeek）显示该段内容的简短摘要，让你明白自己将失去什么。默认关闭。
- 📊 **真实的窗口占用**——根据日志中的 `usage` 显示实际的上下文大小，其中包括
  系统提示词、工具 schema、MCP 以及 `CLAUDE.md`。
- 🗂 **交互式会话选择器**——不带参数运行时，它会（通过 `fzf`）打开一个会话列表
  （可按标题搜索），这样你就不必记住 id。
- 🔓 **解除“已达上下文上限”的封锁**——Claude Code 是根据上一次响应的 `usage` 来
  判断是否到达上限的，而不会重新统计被裁剪后的消息。在一次裁剪之后，ccclean 会把
  该计数器下调 `usage_subtract`（默认 `200k`，`config.json` 中的一个键）——明显
  低于实际删除的量，这样在清理后的第一次请求之前，auto-compact 就不会触发。真实的
  上下文仍然低于上限，于是服务器会接受这次请求，Claude Code 也会根据实际数据重新
  统计计数器。
- 💾 **安全保障**——每次裁剪前都会自动备份，并进行完整性校验、防止删光整段对话，
  以及正确地重新拼接根节点。

---

## 安装

你需要 **Python 3.8+** 和 `pip`。其余的一切（`tiktoken`、`anthropic`、`fzf`）
工具会在首次运行时自行安装。

```bash
git clone https://github.com/Glym143/ccclean.git
cd ccclean
./install.sh
```

`install.sh` 会：

- 为 `ccclean.py` 赋予可执行权限；
- 在你 `PATH` 中第一个可写目录（`/opt/homebrew/bin`、`/usr/local/bin` 或
  `~/.local/bin`）里创建一个 `ccclean` 符号链接——无需 sudo；
- 创建配置文件 `~/.config/ccclean/config.json`（权限 `600`）。

> 如果选中的是 `~/.local/bin` 但它不在你的 `PATH` 中，请把下面这行加入
> `~/.zshrc` / `~/.bashrc`：
> `export PATH="$HOME/.local/bin:$PATH"`

### API 密钥

把你的密钥放进 `~/.config/ccclean/config.json`：

```json
{
  "deepseek_api_key": "sk-...",
  "anthropic_api_key": "sk-ant-..."
}
```

- **`anthropic_api_key`**——精确的 token 计数（默认模式）。
  在 <https://console.anthropic.com/> → API Keys 获取。
- **`deepseek_api_key`**——为被删除内容生成摘要。
  在 <https://platform.deepseek.com/> → API Keys 获取。

你也可以通过环境变量来设置它们（环境变量优先级更高）：
`ANTHROPIC_API_KEY`、`DEEPSEEK_API_KEY`。

没有 Anthropic 密钥时，它会自动回退到离线的 `tiktoken`（近似值）。
没有 DeepSeek 密钥时，则会跳过摘要。

---

## 使用方法

```bash
ccclean                       # pick a session from the list + free 50k (default)
ccclean 30k                   # pick a session + free 30k
ccclean <session-id>          # a specific session + free the default amount
ccclean <session-id> 30k      # a specific session + free 30k
ccclean <session-id> --keep 200k     # keep roughly the last 200k tokens
ccclean <session-id> 50k --dry-run   # show the plan, change nothing
ccclean <session-id> 100k --fast     # fast offline counting (tiktoken)
```

数量可以作为位置参数（`30k`、`50000`、`1.5m`），也可以作为 `--free` / `--keep`
参数给出（参数形式优先）。参数顺序无关紧要。`session-id` 可以缩写（就像在选择器
列表里那样）。查看完整的参数列表：`ccclean -h`。

如果不给出数量，它会使用 `~/.config/ccclean/config.json` 中的 `default_free`
（安装时设为 `50k`；若没有配置文件，内置的回退值为 `10k`）——在那里修改它，
就能一劳永逸地设定你的默认值。

清理完成后，恢复会话：

```bash
claude --resume <session-id>
```

---

## 自动清理 (钩子 + `ccclaude`)

为了免去手动清理，这里有一个自动模式：当上下文被填满、Claude Code 启动一次压缩
（compact）时，钩子会将其拦截，并以运行 `ccclean` 取代有损压缩，随后会话会以
已经卸载的状态重新启动。

`install.sh` 会替你把这一切配置好：

- 安装包装命令 **`ccclaude`**；
- 把钩子放到 `~/.claude/hooks/ccclean-hook.sh`；
- 在 `~/.claude/settings.json` 中为 `PreCompact` 事件注册它，但仅针对**自动**压缩
  （手动的 `/compact` 不受影响——既然是你自己运行的，那压缩本就是你想要的）；
- 启用 `autoCompactEnabled: true`（这是钩子能够自行触发的前提）；
- 设置 `autoCompactWindow: 1000000`——把自动压缩的阈值抬高到接近模型真实的上限
  （Claude Code 把阈值计算为 `window − ~33k`），这样“已达上下文上限”就不会过早触发。

> 它在 Claude Code 内部的工作方式（通过逆向其打包代码得知）：当上一次响应的
> `usage` ≥ `auto-compact-window − output_reserve(≤20k) − 13k` 时，封锁就会触发。
> 因此有两个杠杆可用：抬高窗口（`autoCompactWindow`，由 install.sh 完成）和在清理
> 后下调计数器（`usage_subtract`，由 ccclean 完成）。

**如何使用：** 通过包装命令启动 Claude Code（在终端中）：

```bash
ccclaude --resume <session-id>      # instead of `claude --resume <session-id>`
```

当上下文被填满时的循环：

1. Claude Code 触及上限 → 启动自动压缩。
2. 钩子 `ccclean-hook.sh` 标记该会话并结束 `claude`（压缩被取消）。
3. `ccclaude` 包装命令看到标记 → 等待约 2 秒 → `ccclean <id> --force` →
   重新启动并立即发送提示词：`claude --resume <id> "continue"`。

每个循环的裁剪量按以下优先级设定：

1. `CCCLEAN_FREE` 环境变量（一次性）；
2. `~/.config/ccclean/config.json` 中的 `default_free` 键（持久）；
3. 内置的回退值 `10k`。

```bash
CCCLEAN_FREE=300k ccclaude --resume <id>   # one-off, unload an overflowing session
```

```json
// ~/.config/ccclean/config.json — change the default once and for all
{ "default_free": "30k" }
```

**限制：**

- 只在**终端中**有效，在 VS Code 内不行（钩子会结束 `claude` 进程；VS Code 采用的
  是另一套进程模型）。
- 如果会话正好卡在上限处，一次小幅裁剪（`10k`）可能无法在单个循环里让它脱离上限
  ——这时可以调大 `CCCLEAN_FREE` 来做一次性卸载。

### 主动模式 (`clean_at`)

为了让你彻底不会遇到“已达上下文上限”，还有第二个钩子——挂在 `Stop` 事件上
（每次响应之后触发）。它会从记录中读取当前的 `usage`，如果超过 **`clean_at`** 阈值
（`config.json` 中的一个键，例如 `"940k"`），就会提前运行同样的清理循环
（结束 → `ccclean` → 重启）——此时仍然在上限之内。这样封锁就永远不会发生。
该模式通过配置中是否存在 `clean_at` 来启用。

### 自动续接 (`resume_prompt`)

重启之后，包装命令不只是打开会话——它会**立即向会话发送一条提示词**，让工作在
无需你参与的情况下继续：

```bash
claude --resume <id> "continue"     # claude sends the prompt right at startup
```

这段文字由 `config.json` 中的 **`resume_prompt`** 键设定（默认 `"continue"`）：

```json
{ "resume_prompt": "continue from where you left off" }
```

空字符串（`""`）→ 只恢复会话，不自动发送。

### 钩子安全性

`Stop` / `PreCompact` 钩子会**结束 `claude` 进程**，因此它们只在通过 `ccclaude`
包装命令（会设置 `CCCLEAN_WRAPPED=1`）启动的会话中起作用。在普通会话
（`claude`、VS Code）中，这些钩子不执行任何操作，什么也不会改动。

---

## 工作原理

1. 找到会话文件（通过 id 或交互式选择器）。
2. 重建对话的**活动分支**——从最后一条消息沿着 `parentUuid` 一路回溯到根节点的
   那条链（这正是被加载进上下文的内容）。
3. 统计 token（Anthropic API——精确；`--fast`——tiktoken）。
4. 为所请求的数量找到裁剪点，并将其对齐到一条用户消息的边界（裁剪量不会少于请求量）。
5. 请求确认（若加了 `--summary`，还会通过 DeepSeek 给出被删除内容的简短摘要）。
6. 创建备份 `*.jsonl.bak-<date>`，删除旧消息，重新拼接根节点。
7. 校验结果的完整性。

---

## 面向 AI 智能体

如果运行本工具的是智能体（而非人类），请记住：

- **非交互模式：** `-y`（不需要确认）、`--fast`（不联网，离线计数）。DeepSeek 摘要
  默认关闭——用 `--summary` 启用。你**必须**用一个明确的 `session-id` 指定会话——
  否则会启动交互式选择器并卡住。
  ```bash
  ccclean <session-id> 50k --fast -y
  ```
- **预览而不做改动：** `--dry-run`——打印执行计划（“将释放 ≈ X”、“将保留 ≈ Y”）后
  直接退出，不动任何东西。便于做估算。
- **保证：** 它实际裁剪的量**不会少于**请求量；输出中“将释放 ≈”的数字与真实的
  删除量完全一致。
- **仅限活动分支：** 工具只触及对话当前的线性链。系统提示词、工具 schema、MCP 以及
  `CLAUDE.md` 虽然属于上下文的一部分，但**不会**被裁剪删除（它们并不在 `.jsonl` 里）。
- **默认安全：** 总会创建备份（用 `--no-backup` 关闭）。要回滚的话，把
  `*.jsonl.bak-*` 覆盖到 `*.jsonl` 上即可。
- ⚠️ **务必在目标会话已关闭时再运行：** 处于打开状态的 Claude Code 进程会从内存中
  重写文件，从而覆盖你的改动。工具会通过 `lsof` 检查这一点，并会**拒绝**裁剪一个
  打开着的会话（可用 `--force` 强制覆盖）。

---

## 注意事项

- **务必在被清理的会话已关闭时再运行**（通过 `lsof` 检查；工具会拒绝裁剪打开着的
  会话，可用 `--force` 强制覆盖）。
- 每次裁剪前都会在会话文件旁自动创建一份备份。
- 通过 `tiktoken`（`--fast`）的 token 计数是近似的（对西里尔字母会少算）；要得到
  精确数字，请使用默认模式（Anthropic API）。

---

## 许可证

[MIT](LICENSE) © [Glym143](https://github.com/Glym143)
