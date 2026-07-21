# FK 正运动学校验服务对接说明

本工具的 FK（正运动学）校验通过 **HTTP 调用外部服务** 完成，本仓库**不含**任何运动学实现、URDF 模型或机器人 SDK。FK 服务由数据方（Astribot）部署在自有内网，客户端仅需知道服务的 HTTP 地址。

## 架构

```
astribot-dq (客户侧, 本仓库)                 FK 服务 (服务方内网)
  质检时提取 25 维关节数据  ──HTTP POST──▶   /fk_batch
                          ◀──位姿结果────    (URDF/SDK/运动学库在此)
```

- 请求：`POST {url}`，body `{"joint_states": N×25, "body_names": [...], "robot_type": "s1"}`
- 响应：`{"total_frames": N, "results": {body_name: [[x,y,z,qx,qy,qz,qw], ...]}}`
- 校验逻辑：对比 FK 计算位姿与 HDF5 内 `merge_pose`，位置/姿态误差超阈值即判不一致。

## 配置 FK 服务地址

**通过环境变量注入，优先级高于配置文件。** 不要把真实内网地址写进 `config/validation_config.yaml`。

```bash
export ASTRIBOT_FK_SERVICE_URL="https://fk.<your-internal-domain>/fk_batch"
```

- 已设置：使用该地址进行 FK 校验。
- 未设置且 YAML `fk_service_url` 为空（默认）：**FK 校验自动跳过**，不阻断质检流程，其余检查（时间戳、帧差异、零段等）照常运行。

## 阈值与开关

在 `config/validation_config.yaml`：

| 项 | 说明 |
| --- | --- |
| `check_config.forward_kinematics.enable` | 是否启用 FK 校验（默认 `true`；置 `false` 完全关闭） |
| `check_config.forward_kinematics.level` | `exception`=不一致则判 FAIL；`warning`=仅记录 |
| `fk_position_tolerance_m` | 位置误差容限（米） |
| `fk_orientation_tolerance_deg` | 姿态误差容限（度） |
| `fk_gripper_tolerance` | 夹爪状态误差容限 |

> 注意：`level: exception` 时，FK 服务不可达或数据不一致都会导致文件判 FAIL。若客户环境暂时没有 FK 服务，请将 `enable` 设为 `false`，或不设置 `ASTRIBOT_FK_SERVICE_URL`（留空自动跳过）。

## 验证连通性

```bash
# 健康检查（服务方提供的健康端点）
curl https://fk.<your-internal-domain>/health        # 期望 {"status":"healthy"}

# 设置地址后跑一次质检
export ASTRIBOT_FK_SERVICE_URL="https://fk.<your-internal-domain>/fk_batch"
astribot-dq /path/to/episode.hdf5
# 日志出现 "========= FK checks =========" 即表示已调用 FK 服务
```
