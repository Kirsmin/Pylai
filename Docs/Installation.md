# 安装

> [!TIP]
> 以下安装方式仅适用单机安装。VPS 用户请留足至少 200 MB 内存来维持正常运行。

> [!NOTE]
> 需要提前安装 `Docker`、`Python`
>
> `ManagePylai.pyz` 需要 **Python 3.12 或更高版本**（zipapp 使用 PEP 695 类型别名语法）。若系统自带解释器过旧（如 Ubuntu 22.04 的 `python3.10`），请用 `pyenv`/`venv` 安装 3.12+ 后以 `python3.13 ManagePylai.pyz` 运行；用旧解释器运行会直接提示所需版本，不再抛 `SyntaxError`。

1. 打开 [Releases](https://github.com/Kirsmin/Pylai/releases)

2. 下载 `ManagePylai.pyz`

3. 运行：`python3 ManagePylai.pyz`

4. 按照提示完成安装。注意选择最新版本，不要选择 0.0.x 版本。安装完成后会自动启动 **配置编辑器**。注意修改以下值：

- `[MailTheme.*]`： 默认的验证码邮件模板，注意替换成自己的信息

- `[Email]`、`[Email.Smtp]`：发件人信息

> [!TIP]
> 完成安装后可以在 `ManagePylai.pyz` 完成更新 / 卸载 / 维护等等大部分操作

> [!TIP]
> 需要手工操作容器时可用 compose 直通（自动带上项目名与配置文件）：
>
> ```bash
> python3 ManagePylai.pyz compose ps -a           # 查看各服务状态
> python3 ManagePylai.pyz compose up -d nginx     # 手动拉起对外入口
> python3 ManagePylai.pyz compose logs -f nginx   # 跟踪 nginx 日志
> python3 ManagePylai.pyz start                   # 收敛全部服务（推荐）
> ```