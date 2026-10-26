# AlgoNote v0.1.1：本地部署与验收

**当前已经进入本地部署阶段。** 源码、保存流程、草稿冲突处理、备份恢复和适配代码已在开发环境完成验证；接下来需要在你的电脑上确认 Docker 真实执行、浏览器显示，以及所选 AI 服务。

本应用只需要 Python 3.11+ 和 Docker，不要求 GPU，也不需要安装 Node.js 来使用网页。

## 第一步：获取源码

推荐从 GitHub 克隆到自己有写入权限的目录：

```bash
mkdir -p "$HOME/projects"
git clone https://github.com/volcano-code/OJ.git "$HOME/projects/OJ"
cd "$HOME/projects/OJ"
```

如果使用已下载的 v0.1.1 源码压缩包，也可以按下面的方式解压：

以下命令以 Bash 终端为例，假设压缩包下载到了 `~/Downloads`；实际目录不同就替换解压命令中的压缩包路径。

```bash
mkdir -p "$HOME/projects/algonote-v0.1.1"
python3 -m zipfile -e "$HOME/Downloads/AlgoNote-v0.1.1.zip" "$HOME/projects/algonote-v0.1.1"
cd "$HOME/projects/algonote-v0.1.1/AlgoNote"
```

也可以使用文件管理器解压，然后在解压出的 `AlgoNote` 目录打开终端。使用自己的可写目录可以避免项目、虚拟环境和数据库被其他账户创建后出现权限问题。

如果你已经在 v0.1.0 里录入了自己的题目，先在旧页面导出完整备份。新版本启动后导入其中的 `backup.json`，不要删除旧目录或旧数据库。已有模型配置可以复制到新目录的 `.env`。

## 第二步：检查 Python 与 Docker

```bash
python3 --version
docker info
```

- Python 需要 3.11 或更新版本。
- `docker info` 需要在当前账户下正常返回；只有 Docker 命令本身存在还不够。
- 如果尚未安装 Docker，使用 [Docker 官方 Ubuntu 安装说明](https://docs.docker.com/engine/install/ubuntu/)。如果遇到访问权限问题，参照 [官方 Linux 安装后配置](https://docs.docker.com/engine/install/linux-postinstall/)。
- 应用和启动脚本使用普通账户运行，避免 `sudo bash start.sh` 导致后续文件归 root 所有。

如果默认 `python3` 太旧，但已经有 `python3.12`，首次启动可指定：

```bash
ALGONOTE_PYTHON=python3.12 bash start.sh
```

若创建虚拟环境时报 `ensurepip` / `venv` 缺失，请先补齐对应 Python 版本的 venv 支持。不要删除原项目数据来处理解释器问题。

## 第三步：启动

```bash
bash start.sh
```

首次启动会安装 Python 依赖、建立 `.env`，并准备执行镜像。后续启动会检查镜像中的代码指纹；执行代码变化时会重新构建，匹配时直接复用。`.env` 中的 `ALGONOTE_RUNNER_IMAGE` 自定义镜像名称也会生效。

正常启动后打开：

**http://127.0.0.1:8000**

这个终端保持运行。若 Docker 不可用，网页仍可进行题目管理，但代码执行会明确显示未就绪。

如端口 8000 已被使用，可以在 `.env` 中设置 `ALGONOTE_PORT=8001` 后重新启动，并改用 `http://127.0.0.1:8001`。

## 第四步：实际验证代码运行

另开一个终端，进入同一项目目录。下面使用 GitHub 克隆路径；使用压缩包时改为你的实际解压目录：

```bash
cd "$HOME/projects/OJ"
.venv/bin/python -m algonote doctor --run-check
```

应该看到以下四项实际执行检查通过：

| 检查名 | 内容 |
| --- | --- |
| `python_stdin` | Python 标准输入输出 |
| `cpp_stdin` | C++ 编译与标准输入输出 |
| `python_function` | Python 函数调用，调试打印不污染返回值 |
| `cpp_function` | C++ 函数调用与返回值转换 |

这四项都通过，才说明本机已经具备这两种语言的基本在线执行能力。缺少 Docker、镜像不存在或编译失败会返回非零退出码，不会以跳过充当通过。

需要保留便于排查的报告时执行：

```bash
.venv/bin/python -m algonote doctor --run-check --json > local-check.json
```

报告不包含 API Key 或访问口令。可以把其中未通过的内容发来排查。

如果刚更新代码而没有使用启动脚本，先运行：

```bash
.venv/bin/python -m algonote prepare-runner
```

## 第五步：导入演示题，检查网页

```bash
.venv/bin/python -m algonote import examples/starter.json
```

刷新网页，依次检查：

1. 能看到两数之和、多组整数求和和反转链表三道演示题。
2. 在详情页检查 Python 和 C++ 参考答案，两种语言都应通过已有测试。
3. 点击「再做一次」，确认答案默认隐藏。
4. 输入一段练习代码，等待「草稿已保存」，刷新后确认仍在。
5. 切换语言，确认 C++ 与 Python 草稿分别保存。
6. 在两个标签页同时修改同一道题的同一种语言，旧标签页应提示冲突，并保留当前编辑内容供你选择。
7. 导出备份，确认 ZIP 内存在 `backup.json` 以及可阅读的题面、代码和测试文件。

这一轮也请检查字体、按钮、代码区和窄窗口布局。云端完成的是 DOM 与真实 API 功能检查，尚未验收你的实际浏览器显示。

## 第六步：接入 AI 题解

在 `.env` 填写自己的服务配置：

```dotenv
ALGONOTE_AI_BASE_URL=兼容接口地址
ALGONOTE_AI_API_KEY=自己的密钥
ALGONOTE_AI_MODEL=服务实际支持的模型名称
```

保存后，在正在运行的服务终端按 `Ctrl+C`，重新运行 `bash start.sh`。

打开一道题，先检查参考答案，再生成该语言的中文题解。确认解析对应你提供的代码，并且保存后刷新仍然存在。

`doctor` 中的「已配置/未实测」只说明填写了配置；它不会自动向外部模型发送请求。首次在页面上成功生成和保存题解，才完成真实 AI 服务验收。

## 第七步：可选完整测试

日常使用无需安装测试依赖。希望完成容器隔离和全部回归检查时执行：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m algonote prepare-runner
ALGONOTE_DOCKER_TESTS=1 .venv/bin/python -m pytest -q
```

其中 Docker 测试会实际检查运行超时、输出限制、非 root、只读根文件系统和网络隔离。明确启用 Docker 测试后，Docker 不可用会失败，不会静默跳过。部分宿主机 C++ 适配测试需要宿主机安装 g++；真正的应用运行使用容器内的编译器。

## 什么时候可以开始日常使用

当你完成以下四点，就可以开始把自己的题目正式录入：

- 题目、参考代码、草稿与备份保存正常。
- `doctor --run-check` 的四个执行检查通过。
- 浏览器内能重新做题并看到实际运行结果。
- 真实 AI 服务能生成并保存与你的参考代码一致的解析。

项目源码托管于 [volcano-code/OJ](https://github.com/volcano-code/OJ)。你可以按需要提交自己的 `notebook/` 内容；应用不会自动推送 GitHub，数据库和真实 `.env` 默认由 Git 忽略。
