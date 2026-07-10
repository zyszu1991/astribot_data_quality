# HDF5Validator 校验策略

hdf5_validator.py 对HDF5数据文件的质检校验包括以下策略：

## hdf5 key

```
├── command_poses_dict
│   ├── astribot_arm_left
│   ├── astribot_arm_right
│   ├── astribot_chassis
│   ├── astribot_gripper_left
│   ├── astribot_gripper_right
│   ├── astribot_head
│   ├── astribot_torso
│   ├── command
│   ├── merge_pose
│   └── timestamp
├── images_dict
│   ├── head
│   │   ├── rgb
│   │   ├── rgb_size
│   │   └── rgb_timestamp
│   ├── left
│   │   ├── rgb
│   │   ├── rgb_size
│   │   └── rgb_timestamp
│   └── right
│       ├── rgb
│       ├── rgb_size
│       └── rgb_timestamp
├── joints_dict
│   ├── command_timestamp
│   ├── joints_position_command
│   ├── joints_position_state
│   ├── joints_velocity_state
│   └── state_timestamp
├── poses_dict
│   ├── astribot_arm_left
│   ├── astribot_arm_left_timestamp
│   ├── astribot_arm_right
│   ├── astribot_arm_right_timestamp
│   ├── astribot_chassis
│   ├── astribot_chassis_timestamp
│   ├── astribot_gripper_left
│   ├── astribot_gripper_right
│   ├── astribot_head
│   ├── astribot_head_timestamp
│   ├── astribot_torso
│   ├── astribot_torso_timestamp
│   └── merge_pose
└── time
```

## 时间戳校验

### 1. HDF5 结构校验 (verify_hdf5_structure)
检查必要的数据集是否存在且完整：
- **必需keys**:
  - `time` - 时间戳数据
  - `joints_dict/joints_position_command` - 关节位置命令
  - `joints_dict/joints_position_state` - 关节位置状态
  - `poses_dict/merge_pose` - 合并笛卡尔位姿
  - `command_poses_dict/merge_pose` - 命令笛卡尔位姿
  - `images_dict/{camera}/rgb_timestamp` - 各相机RGB图像时间戳（head, left, right）
- **长度验证**: 所有数据集长度必须与`time`数据集长度一致

### 2. Key数据有效性验证 (verify_key_value)
检查必需key的数据有效性：
- **time数据验证**: 最后时间戳 - 首个时间戳 > 0
- 异常类型：`KeyInvalid`、`KeyNotFound`

### 3. 时间戳重复检查 (check_duplicate_timestamp)
- 统计每个时间戳出现的次数
- 检查最大重复次数是否超过配置阈值 `max_repetition_count`
- 异常类型：`TimestampRepeat`

### 4. 时间戳跳跃检查 (check_jump_timestamp)
- 计算相邻时间戳的差值 (diff)
- 检查是否存在差值超过配置阈值 `max_jump_timestamp` 的跳跃
- 异常类型：`TimestampJump`

### 5. 时长检查 (check_invalid_duration)
- `time`数据的有效性：最后时间戳 - 首个时间戳 > 0
- **期望时长** = 时间戳数量 / `data_frequency`（配置频率）
- **实际时长** = 最后时间戳 - 首个时间戳
- 两者差值超过配置阈值 `duration_threshold` 则失败
- 异常类型：`TimestampInvalidDuration`

### 6. 时间戳对齐检查 (check_mismatch_timestamp)
- 检查所有以 `_timestamp` 结尾的key是否对齐
- 比较各key中同一索引位置的时间戳，最大差值不能超过 `max_diff_timestamp`
- 异常类型：`TimestampMismatch`

# cartesian pose 校验

### 7. 正运动学验证 (verify_pose_with_fk) - 可选
当配置 `enable_fk_check: true` 时执行：
- 对状态数据和命令数据分别进行FK验证
- 根据`joints_dict/joints_position_state`计算FK，与`poses_dict/merge_pose`比较
- 根据`joints_dict/joints_position_command`计算FK，与`command_poses_dict/merge_pose`比较
- 调用FK API（默认http://localhost:8080/fk_batch）计算关节数据对应的正运动学结果
- **Gripper验证**: 检查关节位置误差 ≤ `fk_gripper_tolerance`
- **其他Body验证** (torso, arm_left, arm_right, head)：
  - 位置误差 (xyz) ≤ `fk_position_tolerance_m`
  - 方向误差 (四元数角度差) ≤ `fk_orientation_tolerance_deg`
- 异常类型：`CartesianJointFKMismatch`

## 帧差异检查

### 8. 关节位置状态帧差异检查 (check_joint_state_frame_diff) - 可选
当配置 `check_config.frame_difference.enable: true` 时执行：
- 数据源：`joints_dict/joints_position_state` (Nx25)
- **关节索引分布**（基于 whole_body_dofs = [3, 4, 7, 1, 7, 1, 2]）：
  - 0-2: chassis, 3-6: torso, 7-13: arm_left
  - 14: gripper_left (夹爪), 15-21: arm_right
  - 22: gripper_right (夹爪), 23-24: head
- **计算方式**: 计算相邻帧的关节差值：diff = |frame[i+1] - frame[i]|
- **阈值检查**：
  - 非夹爪关节：不能超过 `joint_pos_frame_diff_threshold`（默认10）
  - 夹爪关节：不能超过 `gripper_joint_frame_diff_threshold`（默认0.1）
    - **日志**：超限情况总是会被记录（ERROR级别）
    - **异常**：仅当 `check_config.frame_difference.sub_checks.gripper_state.enable: true` 时才抛出异常；为false时按配置级别输出日志但通过验证
- **输出**: 最大差异的关节、关节类型、帧索引及使用的阈值
- 异常类型：`JointStateFrameDiffInvalid`

### 9. 关节速度状态帧差异检查 (check_joint_velocity_frame_diff) - 可选
当配置 `check_config.frame_difference.enable: true` 时执行：
- 数据源：`joints_dict/joints_velocity_state` (Nx25)
- **关节索引分布**: 同关节位置状态
- **计算方式**: 计算相邻帧的关节速度差值：diff = |frame[i+1] - frame[i]|
- **阈值检查**：
  - 非夹爪关节：不能超过 `joint_vel_frame_tolerance_deg`
  - 夹爪关节：不能超过 `gripper_joint_vel_frame_tolerance`
    - **日志**：超限情况总是会被记录（ERROR级别）
    - **异常**：仅当 `check_config.frame_difference.sub_checks.gripper_state.enable: true` 时才抛出异常；为false时按配置级别输出日志但通过验证
- **输出**: 最大差异的关节、关节类型、帧索引及使用的阈值
- 异常类型：`JointStateFrameDiffInvalid`

### 10. 关节位置命令帧差异检查 (check_joint_cmd_frame_diff) - 可选
当配置 `check_config.frame_difference.enable: true` 时执行：
- 数据源：`joints_dict/joints_position_command` (Nx25)
- **关节索引分布**: 同上
- **计算方式**: 计算相邻帧的关节差值：diff = |frame[i+1] - frame[i]|
- **阈值检查**：
  - 非夹爪关节：不能超过 `cmd_joint_pos_frame_diff_threshold`（默认30）
  - 夹爪关节：不能超过 `cmd_gripper_joint_frame_diff_threshold`（默认30）
    - **日志**：超限情况总是会被记录（ERROR级别）
    - **异常**：仅当 `check_config.frame_difference.sub_checks.gripper_state.enable: true` 时才抛出异常；为false时按配置级别输出日志但通过验证
- **输出**: 最大差异的关节、关节类型、帧索引及使用的阈值
- 异常类型：`JointCmdFrameDiffInvalid`

### 11. 笛卡尔位姿状态帧差异检查 (check_cartesian_state_frame_diff) - 可选
当配置 `check_config.frame_difference.enable: true` 时执行：
- 数据源：`poses_dict/merge_pose` (Nx37)
- **merge_pose索引分布**（基于 whole_body_cartesian_dofs = [7, 7, 7, 1, 7, 1, 7]）：
  - 0-6: chassis, 7-13: torso, 14-20: arm_left
  - 21: gripper_left (夹爪), 22-28: arm_right
  - 29: gripper_right (夹爪), 30-36: head
- **计算方式**：将merge_pose分类计算差异
  - **位置差异**（7维body的xyz）: 计算相邻帧的欧几里得距离 L2(diff_xyz)
  - **方向差异**（7维body的四元数）: 计算相邻帧的四元数角度差（度数）
  - **夹爪差异**（1维body）: 计算相邻帧的差值 diff = |frame[i+1] - frame[i]|
- **阈值检查**：
  - 位置差异：不能超过 `cartesian_frame_pos_tolerance_m`
  - 方向差异：不能超过 `cartesian_frame_ori_tolerance_deg`
  - 夹爪差异：不能超过 `gripper_joint_frame_tolerance`
    - **日志**：超限情况总是会被记录（ERROR级别）
    - **异常**：仅当 `check_config.frame_difference.sub_checks.gripper_state.enable: true` 时才抛出异常；为false时按配置级别输出日志但通过验证
- **输出**: 最大差异的类型、帧索引及使用的阈值
- 异常类型：`CartesianStateFrameDiffInvalid`

### 12. 笛卡尔位姿命令帧差异检查 (check_cartesian_cmd_frame_diff) - 可选
当配置 `check_config.frame_difference.enable: true` 时执行：
- 数据源：`command_poses_dict/merge_pose` (Nx37)
- **merge_pose索引分布**: 同上
- **计算方式**：同上
- **阈值检查**：
  - 位置差异：不能超过 `cmd_cartesian_frame_pos_tolerance_m`
  - 方向差异：不能超过 `cmd_cartesian_frame_ori_tolerance_deg`
  - 夹爪差异：不能超过 `cmd_gripper_joint_frame_tolerance`
    - **日志**：超限情况总是会被记录（ERROR级别）
    - **异常**：仅当 `check_config.frame_difference.sub_checks.gripper_state.enable: true` 时才抛出异常；为false时按配置级别输出日志但通过验证
- **输出**: 最大差异的类型、帧索引及使用的阈值
- 异常类型：`CartesianCmdFrameDiffInvalid`

### 13. 相机帧差异检查 (verify_camera_frame_diffs) - 可选
当配置 `check_config.frame_difference.enable: true` 时执行：
- **数据来源**: HDF5Processor 的 `extract_video()` 方法在处理视频时计算得出
- **验证流程**:
  1. HDF5Processor 读取 `images_dict/{camera}/rgb` 数据并逐帧计算相邻帧差异
  2. 将结果保存在 VideosAnalysis 对象中，包含每个相机的最大帧差异值
  3. HDF5Processor 返回 `video_analysis.export_results()` 字典，包含结构：
     ```python
     {
         "camera_name": {
             "max_frame_diff": float,
             "max_frame_diff_index": int,
             "max_frame_diff_timestamp": float,
             "num_frames": int
         }
     }
     ```
  4. HDF5Validator 接收该结果字典，调用 `verify_camera_frame_diffs(video_analysis_results)`
- **验证条件**: 每个相机的 `max_frame_diff` 不能超过 `image_frame_diff_threshold`
- **输出**: 仅打印 `max_frame_diff` 最大的相机的值及其相关信息
- **验证对象**: head, left, right 三个相机
- 异常类型：`CameraFrameDiffInvalid`


### 异常类型总览
- `TimestampEmpty` - 时间戳数据为空
- `TimestampRepeat` - 时间戳重复过多
- `TimestampJump` - 时间戳不连续
- `TimestampMismatch` - 时间戳未对齐
- `TimestampInvalidDuration` - 数据时长异常
- `KeyNotFound` - 必需key不存在
- `KeyInvalid` - key数据无效
- `KeySizeIncorrect` - key数据维度不正确
- `CartesianJointFKMismatch` - 笛卡尔坐标与关节状态不匹配
- `JointStateFrameDiffInvalid` - 关节位置状态帧差异过大
- `JointCmdFrameDiffInvalid` - 关节位置命令帧差异过大
- `CartesianStateFrameDiffInvalid` - 笛卡尔位姿状态帧差异过大
- `CartesianCmdFrameDiffInvalid` - 笛卡尔位姿命令帧差异过大
- `CameraFrameDiffInvalid` - 相机帧间隔异常

## 验证流程和架构

### 验证流程概览
HDF5Validator 的 `verify_data()` 方法按以下顺序执行所有质检验证：

```
1. 开始验证
    ↓
2. HDF5结构验证 (verify_hdf5_structure)
    ↓
3. Key数据有效性验证 (verify_key_value)
    ↓
4. 获取所有timestamp keys并验证
    ├─ 检查timestamp keys是否为空
    ├─ 时间戳重复检查 (check_duplicate_timestamp) ✓ 遍历所有keys
    ├─ 时间戳跳跃检查 (check_jump_timestamp) ✓ 遍历所有keys
    └─ 时长检查 (check_invalid_duration) ✓ 遍历所有keys
    ↓
5. 时间戳对齐检查 (check_mismatch_timestamp)
    ↓
6. 正运动学验证 (verify_pose_with_fk) - 可选，需enable_fk_check=true
    ↓
7. 帧差异检查 - 可选，需enable_frame_diff_check=true
    ├─ 关节位置状态帧差异 (check_joint_state_frame_diff)
    ├─ 关节速度状态帧差异 (check_joint_velocity_frame_diff)
    ├─ 关节位置命令帧差异 (check_joint_cmd_frame_diff)
    ├─ 笛卡尔位姿状态帧差异 (check_cartesian_state_frame_diff)
    └─ 笛卡尔位姿命令帧差异 (check_cartesian_cmd_frame_diff)
    ↓
8. 验证完成
```

### 集成验证流程（单个文件）
在 `hdf5_validator.py` 的 `__main__` 中的完整流程：

```python
# 1. 创建验证器
validator = HDF5Validator()

# 2. 创建处理器（用于视频处理和相机帧分析）
processor = HDF5Processor()

# 3. 验证HDF5文件数据完整性
validator.verify_data(file_path)  # 执行步骤1-7

# 4. 提取视频并分析相机帧
output_folder, camera_results = processor.extract_video(file_path)
# camera_results 格式:
# {
#     "head": {"max_frame_diff": float, "max_frame_diff_index": int, ...},
#     "left": {...},
#     "right": {...}
# }

# 5. 验证相机帧差异
validator.verify_camera_frame_diffs(camera_results)  # 执行步骤13

# 验证成功 ✓
```

### 数据流
```
HDF5文件
    ↓
HDF5Processor.extract_video()
    ├─ 读取images_dict中的RGB数据
    ├─ 计算相邻帧差异 (VideosAnalysis)
    └─ 返回 {camera_name: {max_frame_diff, ...}}
    ↓
HDF5Validator.verify_camera_frame_diffs()
    ├─ 检查每个相机的max_frame_diff
    ├─ 打印max_frame_diff最大的相机的值
    └─ 如果超过image_frame_diff_threshold，抛出CameraFrameDiffInvalid
```

## 配置参数说明

### 时间戳检查配置
- `data_frequency` - 数据采样频率（Hz），用于计算期望时长，默认30
- `duration_threshold` - 实际时长与期望时长的最大差值（秒），默认10
- `max_repetition_count` - 时间戳最大重复次数，默认10
- `max_diff_timestamp` - 各timestamp key之间的最大差异（秒），默认0.2
- `max_jump_timestamp` - 时间戳最大跳跃值（秒），默认0.2

### 检查启用配置 (check_config)

检查配置采用分层结构，每个检查项有两个属性：
- `enable: bool` - 是否启用该检查
- `level: str` - 检查失败时的处理级别
  - `"warning"` - 记录警告日志，但不抛出异常（检查通过）
  - `"exception"` - 记录错误日志，并抛出异常（检查失败）

检查配置参数：
- `check_config.timestamp.enable` - 是否启用时间戳检查，默认True
- `check_config.timestamp.level` - 时间戳检查级别（warning/exception），默认warning
- `check_config.forward_kinematics.enable` - 是否启用正运动学验证，默认True
- `check_config.forward_kinematics.level` - 正运动学检查级别，默认warning
- `check_config.frame_difference.enable` - 是否启用帧差异检查，默认True
- `check_config.frame_difference.level` - 帧差异检查级别，默认warning
- `check_config.frame_difference.sub_checks.gripper_state.enable` - 是否启用夹爪状态检查，默认True
- `check_config.frame_difference.sub_checks.gripper_state.level` - 夹爪检查级别（warning/exception），默认warning
  - `"warning"` - 输出错误日志但不抛异常
  - `"exception"` - 输出错误日志并抛异常

### FK验证配置
- `fk_gripper_tolerance` - Gripper关节位置误差容限，默认0.1
- `joint_fk_position_tolerance` - 关节位置误差容限（米），默认0.1
- `joint_fk_orientation_tolerance` - 关节方向误差容限（度），默认10

### 帧差异检查配置
- `image_frame_diff_threshold` - 相机图像帧间隔差异阈值，默认1e4
- `joint_pos_frame_diff_threshold` - 关节位置状态相邻帧差异阈值（非夹爪，角度制），默认10
- `gripper_joint_frame_diff_threshold` - 夹爪位置状态相邻帧差异阈值，默认0.1
- `cmd_joint_pos_frame_diff_threshold` - 关节位置命令相邻帧差异阈值（非夹爪，角度制），默认30
- `cmd_gripper_joint_frame_diff_threshold` - 夹爪位置命令相邻帧差异阈值，默认30
- `cartesian_frame_pos_diff_threshold` - 笛卡尔位姿状态位置相邻帧差异阈值（米），默认0.5
- `cartesian_frame_ori_diff_threshold` - 笛卡尔位姿状态方向相邻帧差异阈值（度），默认10
- `cmd_cartesian_frame_pos_diff_threshold` - 笛卡尔位姿命令位置相邻帧差异阈值（米），默认0.5
- `cmd_cartesian_frame_ori_diff_threshold` - 笛卡尔位姿命令方向相邻帧差异阈值（度），默认10

### 使用方式
```bash
# 验证单个文件
python trans_hdf5/hdf5_validator.py /path/to/file.hdf5

# 验证文件夹内所有HDF5文件（会统计异常）
python trans_hdf5/hdf5_validator.py /path/to/folder
```