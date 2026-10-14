# 内部开发模式

Manager 与 NineClaw-Deploy 统一使用一个开关：

```dotenv
DEV_MODEL=true
```

当前两个源码工作区的内部 `.env` 都保留该行。交付的 env.example 不列出开发开关。变量缺失、为空或为 false 时是生产模式；旧 APP_ENV、DEBUG、DEV_AUTH_* 不再影响 Manager。

本地运行 Manager 时修改其 `.env` 并重启；Docker Compose 部署时修改 Deploy `.env` 后重新创建 Manager 容器，普通 docker restart 不会重新读取宿主机环境文件。Compose 自动通过 env_file 传入变量，没有额外模式锁定。Manager 镜像统一使用 run.py 启动，在开发模式自动 reload，在生产模式按既有 worker 设置运行。容器若要监听宿主源码，仍需源码挂载；模式开关不会改变容器拓扑。

开发登录自动使用 DEFAULT_TENANT_ID。可信浏览器来源从现有 PUBLIC_TRAEFIK_URL、显式 CORS_ORIGINS，以及对应主机的 Vite 5173 端口推导；本机 localhost/127.0.0.1 的 5173/8510 也可用，通配符不能扩大开发来源。

开发用户固定为 nineclaw-dev-admin（超级管理员）、nineclaw-dev-a 和 nineclaw-dev-b（普通成员），没有预设密码。默认自动进入 A，头像菜单可以切换三个账号；已有正式账号保持登录，退出后暂停自动登录。切换后刷新页面清理上个账号的缓存与流连接。账号和数据沿用现有记录，不接管正式用户，不自动恢复被停用或角色已变更的测试账号。

关闭模式后开发会话在后续鉴权时被拒绝，正式账号照常登录。Runtime 已建立的长连接沿用原有撤销机制，不会自动全部断开。开发模式仍执行资源归属和角色检查；WebSearch 始终需要可信鉴权上下文。

DEV_MODEL 控制开发免登录和服务 reload，不会关闭网关资源授权、自动公开内部端口或自动禁用 HTTPS Cookie；这些仍由实际部署地址和网络配置决定。开发入口只用于可信内部环境；知道变量名的部署者仍可主动开启，隐藏配置不构成安全边界。
