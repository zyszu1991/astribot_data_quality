import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CheckItem:
    enable: bool = True
    level: str = "warning"


@dataclass
class FrameDifferenceCheckConfig(CheckItem):
    gripper_state: CheckItem = field(
        default_factory=lambda: CheckItem(enable=True, level="warning")
    )
    camera: CheckItem = field(
        default_factory=lambda: CheckItem(enable=False, level="warning")
    )


@dataclass
class CheckConfig:
    timestamp: CheckItem = field(
        default_factory=lambda: CheckItem(enable=True, level="exception")
    )
    forward_kinematics: CheckItem = field(
        default_factory=lambda: CheckItem(enable=True, level="warning")
    )
    frame_difference: FrameDifferenceCheckConfig = field(
        default_factory=FrameDifferenceCheckConfig
    )


@dataclass
class ValidationConfig:
    data_frequency: int = 30
    duration_threshold: int = 10
    max_repetition_count: int = 10
    max_diff_timestamp: float = 0.2
    max_jump_timestamp: float = 0.2

    check_config: CheckConfig = field(default_factory=CheckConfig)

    # FK check
    fk_service_url: str = ""
    fk_gripper_tolerance: float = 1e-2
    fk_position_tolerance_m: float = 1e-2
    fk_orientation_tolerance_deg: int = 30

    # Frame difference check
    image_frame_tolerance: float = 1e4
    joint_pos_frame_tolerance_deg: float = 10
    gripper_joint_frame_tolerance: float = 0.1
    joint_vel_frame_tolerance_deg: float = 300
    gripper_joint_vel_frame_tolerance: float = 1500
    cmd_joint_pos_frame_tolerance_deg: float = 30
    cmd_gripper_joint_frame_tolerance: float = 30
    cartesian_frame_pos_tolerance_m: float = 0.5
    cartesian_frame_ori_tolerance_deg: float = 10
    cmd_cartesian_frame_pos_tolerance_m: float = 0.5
    cmd_cartesian_frame_ori_tolerance_deg: float = 10

    def is_check_enabled(self, check_type: str, sub_check: str = None) -> bool:
        if check_type == "timestamp":
            return self.check_config.timestamp.enable
        elif check_type == "forward_kinematics":
            return self.check_config.forward_kinematics.enable
        elif check_type == "frame_difference":
            if sub_check is None:
                return self.check_config.frame_difference.enable
            elif sub_check == "gripper_state":
                return self.check_config.frame_difference.gripper_state.enable
            elif sub_check == "camera":
                return self.check_config.frame_difference.camera.enable
        return False

    def get_check_level(self, check_type: str, sub_check: str = None) -> str:
        if check_type == "timestamp":
            return self.check_config.timestamp.level
        elif check_type == "forward_kinematics":
            return self.check_config.forward_kinematics.level
        elif check_type == "frame_difference":
            if sub_check is None:
                return self.check_config.frame_difference.level
            elif sub_check == "gripper_state":
                return self.check_config.frame_difference.gripper_state.level
            elif sub_check == "camera":
                return self.check_config.frame_difference.camera.level
        return "warning"


def _build_check_config_from_raw(check_config_dict: dict) -> CheckConfig:
    timestamp_dict = check_config_dict.get("timestamp", {})
    timestamp = CheckItem(
        enable=timestamp_dict.get("enable", True),
        level=timestamp_dict.get("level", "exception"),
    )

    fk_dict = check_config_dict.get("forward_kinematics", {})
    forward_kinematics = CheckItem(
        enable=fk_dict.get("enable", True),
        level=fk_dict.get("level", "warning"),
    )

    fd_dict = check_config_dict.get("frame_difference", {})
    gripper_dict = fd_dict.get("gripper_state", {})
    gripper_state = CheckItem(
        enable=gripper_dict.get("enable", True),
        level=gripper_dict.get("level", "warning"),
    )
    camera_dict = fd_dict.get("camera", {})
    camera_state = CheckItem(
        enable=camera_dict.get("enable", False),
        level=camera_dict.get("level", "warning"),
    )
    frame_difference = FrameDifferenceCheckConfig(
        enable=fd_dict.get("enable", True),
        level=fd_dict.get("level", "warning"),
        gripper_state=gripper_state,
        camera=camera_state,
    )

    return CheckConfig(
        timestamp=timestamp,
        forward_kinematics=forward_kinematics,
        frame_difference=frame_difference,
    )


def load_validation_config_from_yaml(path: Optional[str] = None) -> ValidationConfig:
    path = path or str(
        Path(__file__).parent.parent / "config" / "validation_config.yaml"
    )
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if "check_config" in raw:
        check_config_dict = raw.pop("check_config")
        raw["check_config"] = _build_check_config_from_raw(check_config_dict)

    return ValidationConfig(**raw)
