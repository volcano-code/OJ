# AlgoNote v0.1.1 验证记录

日期：2026-10-26。

本文件记录 v0.1.1 推送前的开发环境验证。远程 CI 的实际结果请查看 [GitHub Actions](https://github.com/volcano-code/OJ/actions/workflows/ci.yml) 中对应提交的运行记录。

## 本轮实际完成

| 验证 | 实际结果 |
| --- | --- |
| Python 自动化测试完整运行 | 128 passed，4 skipped，0 failures，0 errors；约 26 秒 |
| 前端 JavaScript 语法检查 | `node --check algonote/static/app.js` 通过 |
| 启动脚本语法检查 | `bash -n start.sh` 通过 |
| 前端 DOM 与真实 HTTP API 集成检查 | 15 项通过，0 个未捕获 JavaScript 错误 |
| Docker 缺失时的实际部署自检 | `doctor --run-check --json` 返回退出码 1，明确报告未执行 |
| 首次启动流程复核 | 配置的镜像名、旧镜像重建、目录权限、失败退出码和四类执行自检均已检查 |

完整自动化测试命令：

```bash
.venv/bin/python -m pytest -q --junitxml=verification/pytest.xml
```

原始结果见 `verification/pytest.xml`、`verification/frontend-results.json` 与 `verification/local-preflight-cloud.json`。前两者分别为自动化测试和 DOM/API 检查；最后一份如实记录本次环境缺少 Docker，不能作为容器运行通过的证据。

### 保存与恢复

本轮新增并验证：草稿保存的原子版本比对、两个标签页冲突、相同时间戳下的草稿更新、串行文件同步、删除后不被旧同步任务重新生成、备份历史引用与冲突校验、导入失败回滚，以及重试导入时补齐文件镜像。

已有测试继续覆盖 SQLite 持久化、检索筛选、双语言草稿、题解与测试版本关联、运行范围、失败状态、完整备份恢复、访问口令和跨站写入限制。没有改变数据库表结构。

### 前端交互

使用 jsdom 加实际 FastAPI HTTP 服务，操作真实页面表单和按钮；为复现竞态，定向注入延迟响应和暂时断网。覆盖保存中继续输入并切页、跨标签页冲突与手动处理、离线恢复、过期代码识别响应、双模式测试文本保留，以及保存题解时切换语言。题面中的 HTML/脚本仍按文本处理。

这些检查没有向应用增加生产环境前端依赖，也不等同于真实浏览器视觉验收。

### 执行与 AI 适配

固定开发测试程序继续使用 Python / g++ 实际验证函数适配、数组、字符、链表、树、void、int64 与边界处理。本轮补充 Python 编译阶段语法错误、future 导入与同行语句保留，以及 CPU 超时和文件输出限制分类。

镜像准备流程与错误分支通过受控子进程结果验证；部署自检的四个固定样例已检查输入和调用方式。它们尚未在本环境中的 Docker 内实际执行。

AI 自动化测试使用受控 HTTP 响应，验证请求包含参考代码与验证证据，并检查认证、限流、超时、截断及错误格式处理；没有实际调用外部模型。

## 仍需在本地完成

### 真实 Docker 集成：4 项明确跳过

本次环境没有 Docker。已提供真实 Docker 测试与 GitHub Actions 工作流，但没有将其标记为已通过，也没有让应用在宿主机直接运行用户提交来代替容器。

日常部署先运行四项基本自检：

```bash
.venv/bin/python -m algonote prepare-runner
.venv/bin/python -m algonote doctor --run-check
```

安装测试依赖后，可以完成更全面的容器检查：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
ALGONOTE_DOCKER_TESTS=1 .venv/bin/python -m pytest -q
```

真实 Docker 测试检查 Python / C++ 编译执行、函数适配、超时、输出限制、非 root、只读根文件系统和网络隔离。明确启用后环境不可用会失败，不会静默跳过。

### 真实 AI 服务

需要填入自己的服务地址、模型和密钥，重启后实际生成并保存题解。`doctor` 只报告配置状态，不向外部模型发送请求；配置存在不代表模型已验证可用。

### 浏览器视觉与远程仓库

尚未在真实浏览器验收桌面、手机宽度与代码编辑区排版。请按照 `LOCAL_DEPLOYMENT.md` 进行本地操作检查。

GitHub 仓库为 [volcano-code/OJ](https://github.com/volcano-code/OJ)。源码推送会触发 CI；本文件中的开发环境测试结果不代表远程 CI 已通过。应用尚未公网发布。

## 历史结果与说明

v0.1.0 于 2026-10-22 完成 99 项自动化测试、11 项 DOM/API 检查，并实际执行 3 道随包演示题、两种语言的 16 个固定用例。`verification/examples.json` 保留该次演示题结果，属于历史宿主机适配验证，不作为本次 Docker 验收。

完整测试仍有一条 Starlette TestClient 对 httpx 的弃用提示，不影响通过结果。真实用户数据、虚拟环境和密钥不加入源码包。
