import os
import h5py
import traceback
import numpy as np
from collections import Counter
from typing import List, Dict
import requests
import time
import math

from astribot_dq.file_path import FilePath
from astribot_dq.logger import g_logger
from astribot_dq.schemas import *
from astribot_dq.config import ValidationConfig, load_validation_config_from_yaml


def quaternion_angle_diff(q1, q2):
    """Compute angle difference (degrees) between two quaternion arrays.

    Args:
        q1, q2: shape (n, 4) arrays in [qx, qy, qz, qw] format.
    Returns:
        shape (n,) array of angle differences in degrees.
    """
    q1_norm = q1 / np.linalg.norm(q1, axis=1, keepdims=True)
    q2_norm = q2 / np.linalg.norm(q2, axis=1, keepdims=True)
    dot_product = np.sum(q1_norm * q2_norm, axis=1)
    dot_product = np.clip(dot_product, -1, 1)
    angle_diff = 2 * np.arccos(np.abs(dot_product))
    return angle_diff / math.pi * 180


class HDF5Validator:
    """Validates HDF5 robot data files for quality issues."""

    def __init__(self, config_path: str = None):
        self.config = load_validation_config_from_yaml(config_path)

        self.whole_body_names = [
            "astribot_chassis",
            "astribot_torso",
            "astribot_arm_left",
            "astribot_gripper_left",
            "astribot_arm_right",
            "astribot_gripper_right",
            "astribot_head",
        ]
        self.whole_body_dofs = [3, 4, 7, 1, 7, 1, 2]
        self.gripper_dof_indices = [
            sum(self.whole_body_dofs[:idx])
            for idx, name in enumerate(self.whole_body_names)
            if "gripper" in name
        ]
        self.whole_body_cartesian_dofs = [7, 7, 7, 1, 7, 1, 7]
        self.gripper_cartesian_indices = [
            sum(self.whole_body_cartesian_dofs[:idx])
            for idx, name in enumerate(self.whole_body_names)
            if "gripper" in name
        ]
        self.verify_cartesian_body_names = [
            "astribot_torso",
            "astribot_arm_left",
            "astribot_arm_right",
            "astribot_head",
        ]

    def _handle_check_result(
        self, check_type: str, error_msg: str, exception_class,
        sub_check: str = None, error_details: list = None
    ):
        level = self.config.get_check_level(check_type, sub_check)
        if level == "exception":
            g_logger.error(error_msg)
            raise exception_class("data QC failed", error_msg, error_details or [])
        else:
            g_logger.warning(error_msg)

    def _get_all_keys(self, hdf5_object: h5py.File, prefix: str = "") -> List[str]:
        all_keys = []
        for key in hdf5_object.keys():
            full_key = f"{prefix}/{key}" if prefix else key
            all_keys.append(full_key)
            if isinstance(hdf5_object[key], h5py.Group):
                subgroup_keys = self._get_all_keys(hdf5_object[key], full_key)
                all_keys.extend(subgroup_keys)
        return all_keys

    # --- Public API ---

    def verify_data(self, file_path: str):
        """Run full quality inspection on an HDF5 file."""
        g_logger.info(f"Starting HDF5 data QC: {file_path}")
        file_name = os.path.basename(file_path)

        ignore_key = "poses_dict"
        num_timestamp = 0

        with h5py.File(file_path, "r") as hdf5_obj:
            self._verify_hdf5_structure(hdf5_obj)
            self._verify_key_value(hdf5_obj)

            all_keys = self._get_all_keys(hdf5_obj)
            timestamp_keys = set(
                key for key in all_keys
                if key.endswith("_timestamp") and not key.startswith(ignore_key)
            )

            if len(timestamp_keys) == 0:
                g_logger.warning("No _timestamp keys found")

            # --- Timestamp checks ---
            g_logger.info("========= Timestamp checks =========")
            self._check_invalid_duration(hdf5_obj["time"], "time")

            ignore_keys = set()
            for key in timestamp_keys:
                dataset = hdf5_obj[key]
                if not isinstance(dataset, h5py.Dataset):
                    ignore_keys.add(key)
                    continue
                key_num_timestamp = dataset.shape[0]
                if key_num_timestamp == 0:
                    error_msg = f"[{key}] no data"
                    error_details = [{"key_name": key, "total_count": 0}]
                    self._handle_check_result(
                        "timestamp", error_msg, TimestampEmpty, error_details=error_details
                    )
                num_timestamp = (
                    key_num_timestamp
                    if num_timestamp == 0
                    else min(num_timestamp, key_num_timestamp)
                )
                self._check_duplicate_timestamp(dataset, key)
                self._check_jump_timestamp(dataset, key)

            self._check_mismatch_timestamp(hdf5_obj, timestamp_keys - ignore_keys, num_timestamp)

            # --- FK check ---
            robot_type = FilePath.get_robot_type_from_task(file_name)
            if robot_type is None:
                g_logger.warning("Cannot determine robot type from task name, skipping FK check")
            elif (
                self.config.is_check_enabled("forward_kinematics")
                and self.config.fk_service_url != ""
            ):
                g_logger.info("========= FK checks =========")
                start_time = time.time()
                self._verify_pose_with_fk(hdf5_obj, robot_type)
                g_logger.info(f"FK check took {time.time() - start_time:.5f}s")

            # --- Frame difference checks ---
            if self.config.is_check_enabled("frame_difference"):
                g_logger.info("========= Frame difference checks =========")
                start_time = time.time()
                try:
                    self._check_joint_state_frame_diff(hdf5_obj["joints_dict/joints_position_state"])
                    self._check_joint_velocity_frame_diff(hdf5_obj["joints_dict/joints_velocity_state"])
                    self._check_joint_cmd_frame_diff(hdf5_obj["joints_dict/joints_position_command"])
                    self._check_cartesian_state_frame_diff(hdf5_obj["poses_dict/merge_pose"])
                    self._check_cartesian_cmd_frame_diff(hdf5_obj["command_poses_dict/merge_pose"])
                except (KeyError, ValueError, OSError) as e:
                    g_logger.error(f"Frame difference check failed (missing or invalid data): {e}")
                    self._handle_check_result(
                        "frame_difference",
                        f"Frame difference check skipped: {e}",
                        KeyNotFound,
                        error_details=[{"error": str(e)}],
                    )
                g_logger.info(f"Frame diff check took {time.time() - start_time:.5f}s")

        g_logger.info("Data QC passed!")

    # --- Structure checks ---

    def _verify_hdf5_structure(self, hdf5_obj: h5py.File):
        verified_keys = [
            "time",
            "joints_dict/joints_position_command",
            "joints_dict/joints_position_state",
            "joints_dict/joints_velocity_state",
            "poses_dict/merge_pose",
            "command_poses_dict/merge_pose",
        ]
        camera_names = ["head", "left", "right"]
        for camera in camera_names:
            verified_keys.append(f"images_dict/{camera}/rgb_timestamp")

        for key in verified_keys:
            if hdf5_obj.get(key) is None:
                raise KeyNotFound(f"{key} not found", f"{key} not found", [])

        num_timestamps = hdf5_obj["time"].shape[0]
        for key in verified_keys:
            if hdf5_obj[key].shape[0] != num_timestamps:
                raise TimestampMismatch(
                    f"{key} length mismatch",
                    f"Dataset '{key}' shape {hdf5_obj[key].shape} != time length {num_timestamps}",
                    [],
                )

    def _verify_key_value(self, hdf5_obj: h5py.File):
        try:
            duration = hdf5_obj["time"][-1] - hdf5_obj["time"][0]
        except Exception as e:
            raise KeyInvalid("Invalid time key", f"Invalid time key: {e}", [])
        if duration <= 0:
            raise KeyInvalid("Invalid time key", f"non-positive duration: {duration}", [])

    # --- Timestamp checks ---

    def _check_duplicate_timestamp(self, dataset: h5py.Dataset, key: str) -> bool:
        timestamps = dataset[:]
        total_count = len(timestamps)
        timestamp_counter = Counter(timestamps.flatten())
        most_common = timestamp_counter.most_common(1)
        max_duplicate_count = most_common[0][1] if most_common else 0
        unique_count = len(timestamp_counter)

        g_logger.debug(
            f"[{key}]: total={total_count}, unique={unique_count}, max_dup={max_duplicate_count}"
        )

        if max_duplicate_count > 1:
            duplicate_ratio = max_duplicate_count / total_count
            for ts_value, count in most_common:
                ratio = count / total_count
                g_logger.info(
                    f"[{key}] most common ts: {ts_value}, count: {count}, ratio: {ratio*100:.2f}%"
                )
            if max_duplicate_count > self.config.max_repetition_count:
                error_msg = (
                    f"[{key}] timestamp repeat too high: "
                    f"ts {most_common[0][0]} repeated {max_duplicate_count} times, "
                    f"{duplicate_ratio*100:.2f}% (threshold: {self.config.max_repetition_count})"
                )
                error_details = [{
                    "key_name": key,
                    "total_count": int(total_count),
                    "unique_count": int(unique_count),
                    "max_duplicate_count": int(max_duplicate_count),
                    "duplicate_ratio": float(duplicate_ratio),
                    "duplicate_timestamp": float(most_common[0][0]),
                    "threshold": self.config.max_repetition_count,
                }]
                self._handle_check_result(
                    "timestamp", error_msg, TimestampRepeat, error_details=error_details
                )

    def _check_jump_timestamp(self, dataset: h5py.Dataset, key: str) -> bool:
        timestamps = dataset[:].flatten()
        diffs = np.diff(timestamps)
        jump_indices = np.where(diffs > self.config.max_jump_timestamp)[0]
        g_logger.debug(f"[{key}] max adjacent diff: {np.max(diffs):.4f}")

        if len(jump_indices) > 0:
            idx = np.argmax(diffs)
            error_msg = (
                f"[{key}] timestamp jump at index {idx}: "
                f"{timestamps[idx]} -> {timestamps[idx + 1]}, "
                f"diff: {diffs[idx]} (threshold: {self.config.max_jump_timestamp})"
            )
            error_details = [{
                "key_name": key,
                "jump_count": int(len(jump_indices)),
                "max_jump_threshold": float(self.config.max_jump_timestamp),
                "jump_indices": [int(jdx) for jdx in jump_indices],
            }]
            self._handle_check_result(
                "timestamp", error_msg, TimestampJump, error_details=error_details
            )

    def _check_invalid_duration(self, dataset: h5py.Dataset, key: str) -> bool:
        num_timestamp = dataset.shape[0]
        expected_duration = num_timestamp / self.config.data_frequency
        actual_duration = dataset[-1] - dataset[0]
        diff = abs(actual_duration - expected_duration)
        g_logger.info(
            f"[{key}] expected: {expected_duration:.2f}, actual: {actual_duration:.2f}, diff: {diff:.2f}"
        )
        if diff > self.config.duration_threshold:
            error_msg = (
                f"[{key}] duration anomaly: expected={expected_duration:.2f}, "
                f"actual={actual_duration:.2f}, diff={diff:.2f}"
            )
            error_details = [{
                "key_name": key,
                "expected_duration": float(expected_duration),
                "actual_duration": float(actual_duration),
                "duration_diff": float(diff),
                "threshold": self.config.duration_threshold,
            }]
            self._handle_check_result(
                "timestamp", error_msg, TimestampInvalidDuration, error_details=error_details
            )

    def _check_mismatch_timestamp(self, hdf5_obj, cmp_keys, num_timestamp):
        if len(cmp_keys) == 0:
            error_msg = "No timestamp keys found"
            self._handle_check_result("timestamp", error_msg, TimestampEmpty, error_details=[])
            return

        list_diffs = []
        for idx in range(num_timestamp):
            cmp_values = [hdf5_obj[key][idx] for key in cmp_keys]
            list_diffs.append(max(cmp_values) - min(cmp_values))
        np_diffs = np.array(list_diffs)

        max_diff_frame_idx = np.argmax(np_diffs)
        max_diff = np_diffs[max_diff_frame_idx]

        cmp_values_with_keys = [
            (key, hdf5_obj[key][max_diff_frame_idx]) for key in cmp_keys
        ]
        cmp_values_with_keys.sort(key=lambda x: x[1])
        min_key, min_value = cmp_values_with_keys[0]
        max_key, max_value = cmp_values_with_keys[-1]

        g_logger.debug(
            f"Timestamp alignment max diff: {max_diff:.6f} @frame {max_diff_frame_idx}, "
            f"min='{min_key}'({min_value:.6f}), max='{max_key}'({max_value:.6f})"
        )

        diff_indices = np.where(np_diffs > self.config.max_diff_timestamp)[0]
        if len(diff_indices) > 0:
            idx = np.argmax(np_diffs)
            error_msg = (
                f"Timestamp alignment mismatch: at index {idx}, "
                f"max diff = {np_diffs[idx]} (threshold: {self.config.max_diff_timestamp})"
            )
            error_details = [{
                "mismatch_count": int(len(diff_indices)),
                "max_mismatch_threshold": float(self.config.max_diff_timestamp),
                "mismatch_indices": [int(midx) for midx in diff_indices],
            }]
            self._handle_check_result(
                "timestamp", error_msg, TimestampMismatch, error_details=error_details
            )
        else:
            g_logger.info("Timestamp alignment check passed")

    # --- FK checks ---

    def _verify_pose_with_fk(self, hdf5_obj: h5py.File, robot_type: RobotType):
        self._verify_pose_with_fk_generic(
            hdf5_obj, robot_type, "poses_dict/merge_pose", "joints_dict/joints_position_state"
        )
        self._verify_pose_with_fk_generic(
            hdf5_obj, robot_type, "command_poses_dict/merge_pose", "joints_dict/joints_position_command"
        )

    def _verify_pose_with_fk_generic(
        self, hdf5_obj: h5py.File, robot_type: RobotType,
        merge_pose_key: str, joint_key: str
    ):
        expected_merge_pose_cols = sum(self.whole_body_cartesian_dofs)
        expected_joint_state_cols = sum(self.whole_body_dofs)

        merge_poses = np.array(hdf5_obj[merge_pose_key])
        joint_data = np.array(hdf5_obj[joint_key])

        g_logger.info(
            f"[{joint_key}] merge_pose={merge_poses.shape}, joint={joint_data.shape}"
        )

        if merge_poses.shape[1] != expected_merge_pose_cols:
            raise KeySizeIncorrect(
                f"{merge_pose_key} incorrect shape",
                f"Expected Nx{expected_merge_pose_cols}, got {merge_poses.shape[1]} cols",
                [],
            )
        if joint_data.shape[1] != expected_joint_state_cols:
            raise KeySizeIncorrect(
                f"{joint_key} incorrect shape",
                f"Expected Nx{expected_joint_state_cols}, got {joint_data.shape[1]} cols",
                [],
            )

        success, fk_results = self._forward_kinematic_batch(joint_data.tolist(), robot_type)
        if not success:
            g_logger.warning("FK API call failed, skipping FK check")
            return

        all_passed = True
        merge_start_idx = 0
        joint_start_idx = 0

        for body_name, cartesian_dof, joint_dof in zip(
            self.whole_body_names, self.whole_body_cartesian_dofs, self.whole_body_dofs
        ):
            merge_end_idx = merge_start_idx + cartesian_dof
            joint_end_idx = joint_start_idx + joint_dof
            is_gripper = joint_dof == 1

            if is_gripper:
                gripper_poses_merge = merge_poses[:, merge_start_idx:merge_end_idx].flatten()
                gripper_joints = joint_data[:, joint_start_idx:joint_end_idx].flatten()
                errors = np.abs(gripper_poses_merge - gripper_joints)
                max_error = np.max(errors)
                max_error_frame_id = np.argmax(errors)
                mean_error = np.mean(errors)

                if max_error > self.config.fk_gripper_tolerance:
                    all_passed = False
                    g_logger.warning(
                        f"{body_name} FK result: max_err={max_error:.2f}, "
                        f"mean={mean_error}, frame={max_error_frame_id}, "
                        f"tolerance={self.config.fk_gripper_tolerance}"
                    )
                else:
                    g_logger.info(
                        f"{body_name} FK result: max_err={max_error:.2f}, "
                        f"mean={mean_error}, frame={max_error_frame_id}"
                    )

            elif body_name in self.verify_cartesian_body_names:
                poses_merge = merge_poses[:, merge_start_idx:merge_end_idx]

                if body_name in fk_results["results"]:
                    poses_fk = np.array(fk_results["results"][body_name])
                    pos_errors = np.abs(poses_merge[:, :3] - poses_fk[:, :3])
                    ori_errors = quaternion_angle_diff(poses_merge[:, 3:], poses_fk[:, 3:])
                    max_pos_error = np.max(pos_errors)
                    max_ori_error = np.max(ori_errors)
                    mean_pos_error = np.mean(pos_errors)
                    mean_ori_error = np.mean(ori_errors)

                    if (
                        max_pos_error > self.config.fk_position_tolerance_m
                        or max_ori_error > self.config.fk_orientation_tolerance_deg
                    ):
                        all_passed = False
                        g_logger.warning(
                            f"{body_name} FK: max_pos={max_pos_error:.3f}, "
                            f"mean_pos={mean_pos_error:.3f}, max_ori={max_ori_error:.3f}, "
                            f"mean_ori={mean_ori_error:.3f}"
                        )
                    else:
                        g_logger.info(
                            f"{body_name} FK: max_pos={max_pos_error:.3f}, "
                            f"mean_pos={mean_pos_error:.3f}, max_ori={max_ori_error:.3f}, "
                            f"mean_ori={mean_ori_error:.3f}"
                        )
                else:
                    all_passed = False
                    g_logger.warning(
                        f"{body_name} not found in FK results: {fk_results['results'].keys()}"
                    )

            merge_start_idx = merge_end_idx
            joint_start_idx = joint_end_idx

        if all_passed:
            g_logger.info(f"[{joint_key}] FK check passed!")
        else:
            error_msg = f"[{joint_key}] FK check FAILED: merge_pose and joint_data mismatch"
            self._handle_check_result("forward_kinematics", error_msg, CartesianJointFKMismatch)

    def _forward_kinematic_batch(
        self, joint_states: list, robot_type: RobotType
    ):
        try:
            request_data = {
                "joint_states": joint_states,
                "body_names": self.verify_cartesian_body_names,
                "robot_type": robot_type.value.lower(),
            }
            response = requests.post(
                self.config.fk_service_url, json=request_data, timeout=300
            )
            if response.status_code != 200:
                raise Exception(f"FK API returned {response.status_code}: {response.text}")
            result = response.json()
            return True, result
        except requests.exceptions.ConnectionError as e:
            g_logger.error(f"Cannot connect to FK API ({self.config.fk_service_url}): {e}")
        except Exception as e:
            g_logger.error(f"FK API call failed: {e}")
        return False, {}

    # --- Joint frame difference checks ---

    def _check_joint_frame_diff(
        self, joint_states: h5py.Dataset, thre_joint_degree: float,
        thre_gripper: float, check_name: str, error_exception_class
    ):
        joint_data = np.array(joint_states)
        frame_diffs = np.abs(np.diff(joint_data, axis=0))

        gripper_indices_array = np.array(self.gripper_dof_indices)
        normal_joint_indices = np.array([
            idx for idx in range(joint_data.shape[1])
            if idx not in self.gripper_dof_indices
        ])

        normal_max_diffs = (
            np.max(frame_diffs[:, normal_joint_indices], axis=0)
            if len(normal_joint_indices) > 0
            else np.array([])
        )
        normal_max_indices = (
            np.argmax(frame_diffs[:, normal_joint_indices], axis=0)
            if len(normal_joint_indices) > 0
            else np.array([])
        )

        gripper_max_diffs = (
            np.max(frame_diffs[:, gripper_indices_array], axis=0)
            if len(gripper_indices_array) > 0
            else np.array([])
        )
        gripper_max_indices = (
            np.argmax(frame_diffs[:, gripper_indices_array], axis=0)
            if len(gripper_indices_array) > 0
            else np.array([])
        )

        error_msg_parts = []

        if len(normal_joint_indices) > 0:
            max_normal_local_idx = np.argmax(normal_max_diffs)
            max_normal_global_idx = normal_joint_indices[max_normal_local_idx]
            max_normal_diff = normal_max_diffs[max_normal_local_idx]
            max_normal_frame = normal_max_indices[max_normal_local_idx]
            msg = (
                f"{check_name} - normal joint max diff: idx={max_normal_global_idx}, "
                f"diff={max_normal_diff:.4f}, frame={max_normal_frame}, "
                f"tolerance={thre_joint_degree}"
            )
            if max_normal_diff > thre_joint_degree:
                g_logger.warning(f"{msg}, exceeds threshold")
                error_msg_parts.append(msg)
            else:
                g_logger.info(msg)

        if len(gripper_indices_array) > 0:
            max_gripper_local_idx = np.argmax(gripper_max_diffs)
            max_gripper_global_idx = gripper_indices_array[max_gripper_local_idx]
            max_gripper_diff = gripper_max_diffs[max_gripper_local_idx]
            max_gripper_frame = gripper_max_indices[max_gripper_local_idx]
            msg = (
                f"{check_name} - gripper max diff: idx={max_gripper_global_idx}, "
                f"diff={max_gripper_diff:.4f}, frame={max_gripper_frame}, "
                f"tolerance={thre_gripper}"
            )
            if max_gripper_diff > thre_gripper:
                g_logger.warning(f"{msg}, exceeds threshold")
                error_msg_parts.append(msg)
            else:
                g_logger.info(msg)

        if len(error_msg_parts) > 0:
            error_msg = f"{check_name} frame diff issue: {'; '.join(error_msg_parts)}"
            self._handle_check_result(
                "frame_difference", error_msg, error_exception_class
            )

    def _check_joint_state_frame_diff(self, joint_states: h5py.Dataset):
        self._check_joint_frame_diff(
            joint_states,
            self.config.joint_pos_frame_tolerance_deg,
            self.config.gripper_joint_frame_tolerance,
            "[joints_dict/joints_position_state]",
            JointStateFrameDiffInvalid,
        )

    def _check_joint_velocity_frame_diff(self, joint_velocity: h5py.Dataset):
        self._check_joint_frame_diff(
            joint_velocity,
            self.config.joint_vel_frame_tolerance_deg,
            self.config.gripper_joint_vel_frame_tolerance,
            "[joints_dict/joints_velocity_state]",
            JointStateFrameDiffInvalid,
        )

    def _check_joint_cmd_frame_diff(self, joint_states: h5py.Dataset):
        self._check_joint_frame_diff(
            joint_states,
            self.config.cmd_joint_pos_frame_tolerance_deg,
            self.config.cmd_gripper_joint_frame_tolerance,
            "[joints_dict/joints_position_command]",
            JointCmdFrameDiffInvalid,
        )

    # --- Cartesian frame difference checks ---

    def _check_cartesian_frame_diff(
        self, merge_poses: np.ndarray, pos_threshold: float,
        ori_threshold: float, gripper_threshold: float,
        check_name: str, error_exception_class
    ):
        pos_diffs_list = []
        ori_diffs_all = []
        gripper_diffs = []

        body_pos_diffs = {}
        body_ori_diffs = {}
        body_pos_indices = {}
        body_ori_indices = {}

        merge_start_idx = 0
        for body_idx, cartesian_dof in enumerate(self.whole_body_cartesian_dofs):
            merge_end_idx = merge_start_idx + cartesian_dof
            body_name = self.whole_body_names[body_idx]

            if cartesian_dof == 7:
                poses = merge_poses[:, merge_start_idx:merge_end_idx]
                xyz_diffs = np.linalg.norm(np.diff(poses[:, :3], axis=0), axis=1)
                pos_diffs_list.append(xyz_diffs)

                max_pos = np.max(xyz_diffs) if len(xyz_diffs) > 0 else 0
                max_pos_frame = np.argmax(xyz_diffs) if len(xyz_diffs) > 0 else -1
                body_pos_diffs[body_name] = max_pos
                body_pos_indices[body_name] = max_pos_frame

                quaternions = poses[:, 3:]
                ori_diffs = quaternion_angle_diff(quaternions[:-1], quaternions[1:])
                ori_diffs_all.extend(ori_diffs)

                max_ori = np.max(ori_diffs) if len(ori_diffs) > 0 else 0
                max_ori_frame = np.argmax(ori_diffs) if len(ori_diffs) > 0 else -1
                body_ori_diffs[body_name] = max_ori
                body_ori_indices[body_name] = max_ori_frame

            elif cartesian_dof == 1 and merge_start_idx in self.gripper_cartesian_indices:
                gripper_vals = merge_poses[:, merge_start_idx]
                gripper_diff = np.abs(np.diff(gripper_vals))
                gripper_diffs.append(gripper_diff)

            merge_start_idx = merge_end_idx

        pos_diffs = np.concatenate(pos_diffs_list) if pos_diffs_list else np.array([])
        gripper_diffs_array = np.concatenate(gripper_diffs) if gripper_diffs else np.array([])

        max_pos_diff = np.max(pos_diffs) if len(pos_diffs) > 0 else 0
        max_ori_diff = np.max(ori_diffs_all) if len(ori_diffs_all) > 0 else 0
        max_gripper_diff = np.max(gripper_diffs_array) if len(gripper_diffs_array) > 0 else 0

        max_pos_idx = np.argmax(pos_diffs) if len(pos_diffs) > 0 else -1
        max_ori_idx = np.argmax(ori_diffs_all) if len(ori_diffs_all) > 0 else -1
        max_gripper_idx = np.argmax(gripper_diffs_array) if len(gripper_diffs_array) > 0 else -1

        max_pos_body = (
            max(body_pos_diffs.items(), key=lambda x: x[1])[0]
            if body_pos_diffs else "N/A"
        )
        max_ori_body = (
            max(body_ori_diffs.items(), key=lambda x: x[1])[0]
            if body_ori_diffs else "N/A"
        )

        g_logger.info(
            f"{check_name}: max_pos={max_pos_diff:.4f}({max_pos_body}) @frame{max_pos_idx}, "
            f"max_ori={max_ori_diff:.4f}°({max_ori_body}) @frame{max_ori_idx}, "
            f"max_gripper={max_gripper_diff:.4f} @frame{max_gripper_idx}, "
            f"pos_tol={pos_threshold}, ori_tol={ori_threshold}, gripper_tol={gripper_threshold}"
        )

        error_details = []
        error_msg_parts = []

        if max_pos_diff > pos_threshold:
            error_msg_parts.append(
                f"position diff {max_pos_diff:.4f}({max_pos_body}) exceeds {pos_threshold} @frame{max_pos_idx}"
            )
            error_details.append({
                "type": "position",
                "body": max_pos_body,
                "max_diff": float(max_pos_diff),
                "frame_index": int(max_pos_idx),
                "threshold": float(pos_threshold),
            })

        if max_ori_diff > ori_threshold:
            error_msg_parts.append(
                f"orientation diff {max_ori_diff:.4f}°({max_ori_body}) exceeds {ori_threshold}° @frame{max_ori_idx}"
            )
            error_details.append({
                "type": "orientation",
                "body": max_ori_body,
                "max_diff": float(max_ori_diff),
                "frame_index": int(max_ori_idx),
                "threshold": float(ori_threshold),
            })

        if max_gripper_diff > gripper_threshold:
            gripper_check_enabled = self.config.is_check_enabled(
                "frame_difference", "gripper_state"
            )
            if gripper_check_enabled:
                level = self.config.get_check_level("frame_difference", "gripper_state")
                if level == "exception":
                    error_msg_parts.append(
                        f"gripper diff {max_gripper_diff:.4f} exceeds {gripper_threshold} @frame{max_gripper_idx}"
                    )
                    error_details.append({
                        "type": "gripper",
                        "max_diff": float(max_gripper_diff),
                        "frame_index": int(max_gripper_idx),
                        "threshold": float(gripper_threshold),
                    })

        if len(error_msg_parts) > 0:
            error_msg = f"Frame diff issue: {'; '.join(error_msg_parts)}"
            self._handle_check_result(
                "frame_difference", error_msg, error_exception_class,
                error_details=error_details
            )
        else:
            g_logger.info(f"{check_name} passed")

    def _check_cartesian_state_frame_diff(self, cartesian_poses: h5py.Dataset):
        self._check_cartesian_frame_diff(
            np.array(cartesian_poses),
            self.config.cartesian_frame_pos_tolerance_m,
            self.config.cartesian_frame_ori_tolerance_deg,
            self.config.gripper_joint_frame_tolerance,
            "[poses_dict/merge_pose]",
            CartesianStateFrameDiffInvalid,
        )

    def _check_cartesian_cmd_frame_diff(self, cartesian_poses: h5py.Dataset):
        self._check_cartesian_frame_diff(
            np.array(cartesian_poses),
            self.config.cmd_cartesian_frame_pos_tolerance_m,
            self.config.cmd_cartesian_frame_ori_tolerance_deg,
            self.config.cmd_gripper_joint_frame_tolerance,
            "[command_poses_dict/merge_pose]",
            CartesianCmdFrameDiffInvalid,
        )

    def verify_camera_frame_diffs(self, video_analysis_results: Dict):
        if (
            not self.config.check_config.frame_difference.enable
            or not self.config.check_config.frame_difference.camera.enable
        ):
            return

        invalid_results = {}
        max_camera = None
        max_frame_diff = -1

        for camera_name, result in video_analysis_results.items():
            if result["max_frame_diff"] > max_frame_diff:
                max_frame_diff = result["max_frame_diff"]
                max_camera = camera_name
            if result["max_frame_diff"] > self.config.image_frame_tolerance:
                invalid_results[camera_name] = result

        if max_camera is not None:
            result = video_analysis_results[max_camera]
            if result["max_frame_diff"] > self.config.image_frame_tolerance:
                g_logger.error(
                    f"Camera {max_camera} frame interval anomaly: "
                    f"max_diff={result['max_frame_diff']:.2f} exceeds threshold "
                    f"{self.config.image_frame_tolerance}, "
                    f"ts={result['max_frame_diff_timestamp']}, idx={result['max_frame_diff_index']}"
                )
            else:
                g_logger.info(
                    f"Camera {max_camera} frame interval normal: "
                    f"max_diff={result['max_frame_diff']:.2f} < {self.config.image_frame_tolerance}"
                )

        if len(invalid_results) > 0:
            error_msg = (
                f"Camera frame diff exceeded: {list(invalid_results.keys())}"
            )
            error_details = [{
                "invalid_cameras": list(invalid_results.keys()),
                "details": invalid_results,
            }]
            self._handle_check_result(
                "frame_difference", error_msg, CameraFrameDiffInvalid,
                error_details=error_details
            )
