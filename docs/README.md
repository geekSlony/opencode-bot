## 运行指南
1. 拉取代码
`git clone git@github.com:Ninja1957/opencode-bot.git`

2. 安装环境
`conda create -n opcode-bot-py310 python=3.10.20`
`pip install -r requirements.txt `

3. 开始配置
- 飞书里在应用里新建自己的机器人，然后配置相关权限
- 仓库内拷贝.env.example到.env，并配置必填项，主要包含飞书相关的key

4. 运行
- python run.py (⚠️⚠️⚠️ 强烈建议在linux机器上使用tmux进行启动服务，参考：python3 run.py > full.log 2>&1)
- 运行成功后如下图

5. 用户级长期运行（不污染系统）
- 启用自启动与自动拉起（当前用户 crontab）：
`scripts/opencode-botctl.sh autostart-enable`
- 查看状态：
`scripts/opencode-botctl.sh autostart-status`
- 关闭自启动：
`scripts/opencode-botctl.sh autostart-disable`

6. 飞书常用命令
- `/session_list` 或 `/sl`：查看可绑定会话
- `/session_all` 或 `/sa`：查看全部会话（在线+离线）
- `/session_new [目录]` 或 `/sn [目录]`：无会话时主动创建并尝试自动绑定
- `/bind <序号|session_id>`：绑定会话
- `/history [session_id] [条数]`：查看会话最近历史（默认当前绑定，默认10条）
- `/current`：查看当前绑定
- `/session_unbind`：解绑

7. 飞书开放平台必配项（长连接模式）
- 事件与回调里勾选：`im.message.receive_v1`
- 事件与回调里勾选：`card.action.trigger`（或 `p2_card_action_trigger`）
- 完成后到“版本管理与发布”发布到当前可见范围

8. 按钮报错兜底
- 如果点击“绑定并继续”报错（如 `200340`），先直接用命令绑定：`/bind <序号>` 或 `/bind <session_id>`
- 之后再检查第 7 步的事件订阅与发布状态

<img src="./images/success_verify.png" alt="opencode-bot icon" width="540" />















