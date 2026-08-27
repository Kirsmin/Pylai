# 安装

> [!TIP]
> 以下安装方式仅适用单机安装。VPS 用户请留足至少 200 MB 内存来维持正常运行。

> [!NOTE]
> 需要提前安装 `Docker`、`Python`

1. 打开 [Releases](https://github.com/Kirsmin/Pylai/releases)

2. 下载 `ManagePylai.py`

3. 运行：`python3 ManagePylai.py`

4. 按照提示完成安装。注意选择最新版本，不要选择 0.0.x 版本。安装完成后会自动启动 **配置编辑器**。注意修改以下值：

- `[MailTheme.*]`： 默认的验证码邮件模板，注意替换成自己的信息

- `[Email]`、`[Email.Smtp]`：发件人信息

> [!TIP]
> 完成安装后可以在 `ManagePylai.py` 完成更新 / 卸载 / 维护等等大部分操作