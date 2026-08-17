<div align="center">
# Pylai!

_✨简单单机 Docker 部署的 OAuth2（客户端/服务端）/OIDC 用户系统✨_
</div>

> [!CAUTION]
> 此项目仍然处于开发状态，可能频繁破坏性变更，目前不建议真实环境使用

## 快速部署

1. 安装 `Docker`

2. 在发布页下载最新的 ManagePylai.py 和 tar 文件，放在同一目录

3. 执行 `python ManagePylai.py`，按照提示操作即可

## 开发 / 调试
> [!TIP]
> 推荐提前配置代理工具，或者使用镜像源替代

1. 安装 Docker、Pnpm、Dotnet 工具链

2. 拉取本仓库 `git clone https://github.com/Kirsmin/Pylai.git`

3. 进入 UI/ AdminUI/ 页面，输入 `pnpm install` 部署

4. 运行 `python start-dev.py`

## 协议

本项目使用的依赖协议见 `UI/src/views/About.vue`，文档待完善

项目主体采用 MIT 协议

## 说明

> [!WARNING]
> 本项目大量使用 AI 编码，可能存在不稳定行为

> [!NOTE]
> 文档待完善