# 代码审查修复日志 - 2026-07-14

根据 `data-quality-code-review-701-2026-07-14.md` 审查报告实施的修复。

## 🔴 严重问题修复 (P0)

### R1 - quaternion 全零检测漏洞 + 全零段专项检测 ✅

**问题**: `quaternion_angle_diff` 对全零四元数除以零范数产生 NaN，导致 `NaN > threshold` 恒为 False，锁定部件全零数据假通过。

**修复**:
1. **quaternion_angle_diff 函数**:
   - 添加 `QUATERNION_MIN_NORM = 1e-6` 常量
   - 在归一化前检查范数，范数 < 1e-6 的行返回 `inf` 而非 NaN
   - 确保 `inf > threshold` 正确触发失败
   
2. **全零/常零段专项检测**:
   - 新增 `_check_command_pose_zero_segments()` 方法
   - 检测 command_poses_dict/merge_pose 中各 7-DOF body 的三种异常：
     - Position (xyz) 全近零（max < 1e-6）
     - Quaternion 全退化（norm < 1e-6）
     - 整段常数（variance < 1e-12）
   - 新增异常类型 `CommandPoseZeroSegment`，exception 级别强制抛出
   
3. **测试**:
   - 新增 `test_all_zero_command_pose_detected` 回归测试
   - 构造 arm_left 全零场景，验证能正确拦截

**文件**:
- `astribot_dq/validator.py` (quaternion_angle_diff, _check_command_pose_zero_segments)
- `astribot_dq/schemas.py` (CommandPoseZeroSegment)
- `tests/test_smoke.py` (test_all_zero_command_pose_detected)

---

### R2 - 时间戳对齐性能优化（向量化）✅

**问题**: `_check_mismatch_timestamp` 逐帧逐 key 用 `hdf5_obj[key][idx]` 索引，20000 帧耗时 3.376s，向量化后 0.0014s（约 2400 倍差距）。

**修复**:
- 一次性读取所有 timestamp 数组到内存：`{key: hdf5_obj[key][:num_timestamp] for key in cmp_keys}`
- Stack 成 (num_keys, num_timestamp) 矩阵，用 `np.max/np.min` 向量化计算每帧的 max-min
- 禁止逐元素 HDF5 索引

**文件**:
- `astribot_dq/validator.py` (_check_mismatch_timestamp)

---

## 🟡 改进项修复

### Y3 - 机型正则 bug ✅

**问题**: `S1_u` 被误判成 `S1`，因为正则交替 `S0|S1|S1_u` 中 `S1` 先匹配。

**修复**:
- `get_robot_type_from_task` 按 robot type 长度降序排列：`sorted([rt.value for rt in RobotType], key=len, reverse=True)`
- 正则变为 `S1_u|S1|S0` 顺序，最长优先匹配

**测试**:
- 新增 `test_robot_type_extraction_y3_regression` 验证 S1_u/S1/S0 都能正确提取

**文件**:
- `astribot_dq/file_path.py` (get_robot_type_from_task)
- `tests/test_smoke.py` (TestFilePath)

---

### Y5 - 帧差异 argmax 帧号失真 ✅

**问题**: `_check_cartesian_frame_diff` 中 `ori_diffs_all` 跨 body 拼接成一维数组，`np.argmax(ori_diffs_all)` 得到的是全局索引，不对应真实帧号。`body_ori_indices` 字典有正确的帧号但未使用。

**修复**:
- 先从 `body_ori_diffs` 找到最大值所属的 body
- 再从 `body_ori_indices[max_ori_body]` 取该 body 内的真实帧号
- 同样修复 position 的逻辑（用 `body_pos_indices`）

**文件**:
- `astribot_dq/validator.py` (_check_cartesian_frame_diff)

---

### Y4 - FK 检查失败静默跳过 ✅

**问题**: FK API 连接失败时仅 `g_logger.warning` 并 return，与配置中 `forward_kinematics.level = "exception"` 语义冲突。

**修复**:
- FK API 失败时调用 `_handle_check_result("forward_kinematics", ..., CartesianJointFKMismatch)`
- 尊重配置级别，level="exception" 时抛出异常

**测试影响**:
- 测试环境无 FK API，需在测试中显式 disable FK：`validator.config.check_config.forward_kinematics.enable = False`

**文件**:
- `astribot_dq/validator.py` (_verify_pose_with_fk_generic)
- `tests/test_smoke.py` (test_valid_file_passes, test_all_zero_command_pose_detected)

---

### Y2 - error_details 列表设上限 ✅

**问题**: 大文件下 `jump_indices`、`mismatch_indices` 可能有数万条，error_details 撑爆内存。

**修复**:
- 添加 `MAX_ERROR_DETAILS_ITEMS = 1000` 常量
- `_check_jump_timestamp` 和 `_check_mismatch_timestamp` 中截断索引列表：
  - `capped_indices = indices[:MAX_ERROR_DETAILS_ITEMS].tolist()`
  - 添加 `"truncated": bool` 标志位

**文件**:
- `astribot_dq/validator.py` (_check_jump_timestamp, _check_mismatch_timestamp)

---

### Y6 - 删除死代码 SafeHDF5Reader ✅

**问题**: `astribot_dq/read_hdf5.py` 中的 `SafeHDF5Reader` 类完全未使用。

**修复**:
- 删除整个文件 `astribot_dq/read_hdf5.py`

**文件**:
- 删除 `astribot_dq/read_hdf5.py`

---

### Y7 - 清理未使用 report_retry_queue 表 ✅

**问题**: `invalid_data_db.py` 创建了 `report_retry_queue` 表和索引，cleanup 里有 DELETE，但无任何 INSERT/SELECT 使用。

**修复**:
- 删除表的 CREATE TABLE 和 CREATE INDEX 语句
- 删除 cleanup 中的对应 DELETE 语句

**文件**:
- `astribot_dq/invalid_data_db.py` (_init_database, clean_old_records)

---

## ⚠️ 需用户确认项 - 已确认

### 时间戳对齐语义

**报告指出**: 代码实现"各 timestamp key 互相对齐"（max-min），但外部《HDF5 → LeRobot v3 映射规则》第3节写"以 time 为基准"。

**用户决策**: **保持现状（互相对齐）**，与本仓库内部文档一致，不改动。

---

## 测试覆盖

- ✅ 所有原有测试通过（7 个）
- ✅ 新增 R1 回归测试（全零 command_pose 检测）
- ✅ 新增 Y3 回归测试（S1_u 机型提取）
- **最终**: 9 个测试全部通过

---

## 建议后续工作（报告中未本次实施的 P2 项）

1. 补充 FK / 帧差异 / 机型分类的单元测试，提升覆盖率
2. 将 R1/Y3/Y5 作为回归用例固化（已部分完成 R1/Y3）
3. 考虑 Y1（字符串前缀硬编码排除 key）的重构，改为配置驱动

---

## 修改统计

- 修改文件: 5 个
- 删除文件: 1 个
- 新增异常类型: 1 个 (CommandPoseZeroSegment)
- 新增测试: 2 个
- 修复的严重 bug: 2 个（R1, R2）
- 修复的改进项: 5 个（Y2, Y3, Y4, Y5, Y6/Y7）
