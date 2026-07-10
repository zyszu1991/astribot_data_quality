# HDF5 质量校验脚本使用指南

## 概述

`tools/validate_hdf5.py` 是一个独立的 HDF5 质量校验脚本，**仅执行数据校验**，不涉及视频提取、图像压缩、NAS 上传等操作。底层调用 `HDF5Validator.verify_data()`，支持单文件和批量目录两种模式。

## 前置条件

### 1. Python 依赖

确保以下 Python 包已安装：

- `h5py`
- `numpy`
- `requests`
- `PyYAML`

安装命令：

```bash
pip install h5py numpy requests PyYAML
```

### 2. 配置文件

校验阈值和检查级别由 `config/validation_config.yaml` 控制：

| 检查类别 | 默认级别 | 配置文件位置 |
|---------|---------|-------------|
| 时间戳校验 | `exception` | `validation_config.yaml` line 2-6 |
| 正运动学(FK)校验 | `exception` | `validation_config.yaml` line 7-10 |
| 帧差异校验 | `warning` | `validation_config.yaml` line 11-23 |

校验前请根据实际需求调整阈值参数。

### 3. FK 服务（可选）

FK 校验依赖 Docker 化的 ROS 正运动学服务。如果 `docker-compose.yml` 中 `visualize_ee` 服务未启动，FK 检查会被自动跳过，不会阻断校验流程。

启动 FK 服务：

```bash
docker-compose up -d
```

## 执行步骤

### 步骤 1：进入项目根目录

```bash
cd /Users/gabrizhao/Documents/projects/astribot_upload_data_v2
```

### 步骤 2：单文件校验

校验单个 HDF5 文件：

```bash
python3 tools/validate_hdf5.py /path/to/episode_001.hdf5
```

**输出示例（通过）：**

```text
[INFO] Validation config: config/validation_config.yaml
[INFO] FK service URL: http://localhost:8080/fk_batch
[INFO] 开始对HDF5文件进行数据质检: /path/to/episode_001.hdf5
[INFO] ========= 开始时间戳检查 =========
[INFO] ========= 开始FK检查 =========
[INFO] FK验证通过！
[INFO] ========= 开始帧差异检查 =========
[INFO] [poses_dict/merge_pose]通过
[INFO] 数据质检通过!
[INFO] PASS: /path/to/episode_001.hdf5
```

**输出示例（未通过）：**

```text
[ERROR] 时间戳对齐检查发现不匹配: 在索引 42 处，最大差值为 0.35 (阈值: 0.2)
[ERROR] FAIL: /path/to/episode_bad.hdf5  [TimestampMismatch] 时间戳对齐检查发现不匹配
```

**退出码**：
- `0` — 校验通过
- `1` — 校验失败

### 步骤 3：批量校验目录

校验目录下所有 HDF5 文件（递归搜索 `.h5` 和 `.hdf5` 文件）：

```bash
python3 tools/validate_hdf5.py /path/to/hdf5_directory/
```

**输出示例：**

```text
[INFO] Validation config: config/validation_config.yaml
[INFO] FK service URL: http://localhost:8080/fk_batch
[INFO] Found 15 HDF5 files in /path/to/hdf5_directory/
[INFO] [1/15] Validating: episode_001.hdf5
[INFO] PASS: /data/episodes/episode_001.hdf5
[INFO] [2/15] Validating: episode_002.hdf5
[ERROR] FAIL: /data/episodes/episode_002.hdf5  [TimestampRepeat] 时间戳重复过多
...
======================================================================
VALIDATION SUMMARY
======================================================================
  Total files:  15
  Passed:       12
  Failed:       3

  Failed files:
    - /data/episodes/episode_002.hdf5
      [TimestampRepeat] [time] 时间戳 12345 重复了 50 次
    - /data/episodes/episode_007.hdf5
      [CartesianJointFKMismatch] FK验证失败
    - /data/episodes/episode_013.hdf5
      [CartesianStateFrameDiffInvalid] 位置差异 0.82(astribot_arm_left) 超过阈值 0.5
======================================================================
```

**退出码**：
- `0` — 所有文件校验通过
- `1` — 存在校验失败的文件

## 校验内容详解

脚本执行 `verify_data()` 中的四轮检查，按顺序执行（前一轮失败则不再继续）：

```text
verify_data(file_path)
  ├── I.   结构校验
  │        ├── 必须 key 存在性检查
  │        └── 所有 key 行数对齐检查
  ├── II.  时间戳校验（4 项子检查）
  │        ├── 时长异常 (_check_invalid_duration)
  │        ├── 重复时间戳 (_check_duplicate_timestamp)
  │        ├── 时间戳跳跃 (_check_jump_timestamp)
  │        └── 多 key 对齐 (_check_mismatch_timestamp)
  ├── III. 正运动学(FK)校验
  │        ├── state:  merge_pose vs joints_position_state
  │        └── command: merge_pose vs joints_position_command
  └── IV.  帧差异校验（5 项子检查）
           ├── 关节位置帧差异
           ├── 关节速度帧差异
           ├── 关节命令帧差异
           ├── 笛卡尔状态帧差异
           └── 笛卡尔命令帧差异
```

### 各检查项默认阈值

#### 时间戳

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `data_frequency` | 30 Hz | 采集频率 |
| `duration_threshold` | 2 s | 时长异常阈值 |
| `max_repetition_count` | 10 | 单帧最大允许重复次数 |
| `max_jump_timestamp` | 0.2 s | 相邻帧最大允许时间跳变 |
| `max_diff_timestamp` | 0.2 s | 同帧不同 key 最大允许时间差 |

#### 正运动学 (FK)

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `fk_gripper_tolerance` | 10 | 夹爪状态允许误差 |
| `fk_position_tolerance_m` | 0.1 m | 位置允许误差 |
| `fk_orientation_tolerance_deg` | 10 deg | 方向允许误差 |

#### 帧差异

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `joint_pos_frame_tolerance_deg` | 10 deg | 关节位置帧差异阈值 |
| `joint_vel_frame_tolerance_deg` | 300 deg/s | 关节速度帧差异阈值 |
| `cmd_joint_pos_frame_tolerance_deg` | 30 deg | 命令关节帧差异阈值 |
| `cartesian_frame_pos_tolerance_m` | 0.5 m | 笛卡尔位置帧差异阈值 |
| `cartesian_frame_ori_tolerance_deg` | 10 deg | 笛卡尔方向帧差异阈值 |

## 错误类型对照表

| 异常类 | 含义 | 所属检查 |
|--------|------|---------|
| `TimestampEmpty` | 时间戳数据为空 | 时间戳 |
| `TimestampRepeat` | 时间戳重复过多 | 时间戳 |
| `TimestampJump` | 时间戳出现跳跃 | 时间戳 |
| `TimestampMismatch` | 多数据源时间戳不对齐 | 时间戳 |
| `TimestampInvalidDuration` | 时长异常 | 时间戳 |
| `CartesianJointFKMismatch` | 笛卡尔位姿与 FK 计算结果不一致 | FK |
| `JointStateFrameDiffInvalid` | 关节状态帧差异过大 | 帧差异 |
| `JointCmdFrameDiffInvalid` | 关节命令帧差异过大 | 帧差异 |
| `CartesianStateFrameDiffInvalid` | 笛卡尔状态帧差异过大 | 帧差异 |
| `CartesianCmdFrameDiffInvalid` | 笛卡尔命令帧差异过大 | 帧差异 |

## 自定义检查配置

修改 `config/validation_config.yaml` 中的 `check_config` 区域即可控制各项检查的开关和级别：

```yaml
check_config: {
  "timestamp": {
    "enable": true,      # true | false
    "level": exception   # "warning" 或 "exception"
  },
  "forward_kinematics": {
    "enable": true,
    "level": exception
  },
  "frame_difference": {
    "enable": true,
    "level": warning,
    "gripper_state": {
      "enable": true,
      "level": warning
    }
  }
}
```

- `warning`：仅记录日志，不中断校验流程
- `exception`：记录日志并抛出异常，该文件标记为校验失败
