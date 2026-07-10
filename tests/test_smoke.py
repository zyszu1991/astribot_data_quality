"""Smoke tests for the astribot-dq package.

Creates a synthetic HDF5 file with valid data and runs the validator.
"""

import os
import sys
import tempfile
import h5py
import numpy as np
import pytest

# Ensure the package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from astribot_dq.validator import HDF5Validator
from astribot_dq.schemas import QualityCheckError


# Robot body configuration (from the real robot spec)
WHOLE_BODY_DOFS = [3, 4, 7, 1, 7, 1, 2]          # total = 25
WHOLE_BODY_CARTESIAN_DOFS = [7, 7, 7, 1, 7, 1, 7]  # total = 37

NUM_FRAMES = 100
FREQUENCY = 30  # Hz


def create_synthetic_hdf5(filepath: str, num_frames: int = NUM_FRAMES):
    """Create a minimal valid HDF5 file matching the expected robot data schema."""
    with h5py.File(filepath, "w") as f:
        # Timestamps: 30 Hz, monotonically increasing
        timestamps = np.arange(num_frames, dtype=np.float64) / FREQUENCY
        f.create_dataset("time", data=timestamps)

        # Joints dict
        jd = f.create_group("joints_dict")
        jd.create_dataset("joints_position_state", data=np.random.randn(num_frames, sum(WHOLE_BODY_DOFS)) * 0.01)
        jd.create_dataset("joints_position_command", data=np.random.randn(num_frames, sum(WHOLE_BODY_DOFS)) * 0.01)
        jd.create_dataset("joints_velocity_state", data=np.random.randn(num_frames, sum(WHOLE_BODY_DOFS)) * 0.1)
        jd.create_dataset("state_timestamp", data=timestamps)
        jd.create_dataset("command_timestamp", data=timestamps)

        # Poses dict
        pd = f.create_group("poses_dict")
        merge_pose = np.random.randn(num_frames, sum(WHOLE_BODY_CARTESIAN_DOFS)) * 0.01
        # Normalize quaternion columns (indices 3-6 for each 7-dof body)
        for start in range(0, sum(WHOLE_BODY_CARTESIAN_DOFS), 7):
            if start + 7 <= merge_pose.shape[1]:
                q = merge_pose[:, start + 3 : start + 7]
                norms = np.linalg.norm(q, axis=1, keepdims=True)
                merge_pose[:, start + 3 : start + 7] = q / norms
        pd.create_dataset("merge_pose", data=merge_pose)

        # Add timestamp keys for each body
        body_names = [
            "astribot_chassis", "astribot_torso", "astribot_arm_left",
            "astribot_gripper_left", "astribot_arm_right", "astribot_gripper_right",
            "astribot_head",
        ]
        for name in body_names:
            pd.create_dataset(f"{name}_timestamp", data=timestamps)

        # Command poses dict
        cpd = f.create_group("command_poses_dict")
        cmd_merge_pose = np.random.randn(num_frames, sum(WHOLE_BODY_CARTESIAN_DOFS)) * 0.01
        for start in range(0, sum(WHOLE_BODY_CARTESIAN_DOFS), 7):
            if start + 7 <= cmd_merge_pose.shape[1]:
                q = cmd_merge_pose[:, start + 3 : start + 7]
                norms = np.linalg.norm(q, axis=1, keepdims=True)
                cmd_merge_pose[:, start + 3 : start + 7] = q / norms
        cpd.create_dataset("merge_pose", data=cmd_merge_pose)

        # Images dict (camera timestamps)
        imd = f.create_group("images_dict")
        for cam in ["head", "left", "right"]:
            cam_group = imd.create_group(cam)
            cam_group.create_dataset("rgb_timestamp", data=timestamps)
            cam_group.create_dataset("rgb_size", data=np.ones((num_frames, 2), dtype=np.int32) * 640)


class TestHDF5Validator:
    """Smoke tests for HDF5Validator."""

    def test_valid_file_passes(self):
        """A synthetically valid file should pass all checks."""
        with tempfile.NamedTemporaryFile(
            suffix=".hdf5", prefix="20250101_Test_S1_01_", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            create_synthetic_hdf5(tmp_path)
            validator = HDF5Validator()

            # Should not raise
            validator.verify_data(tmp_path)

        finally:
            os.unlink(tmp_path)

    def test_missing_key_raises(self):
        """A file missing a required key should raise KeyNotFound."""
        with tempfile.NamedTemporaryFile(
            suffix=".hdf5", prefix="20250101_Test_S1_01_", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            with h5py.File(tmp_path, "w") as f:
                f.create_dataset("time", data=np.arange(10, dtype=np.float64) / FREQUENCY)
                # Missing all other required keys

            validator = HDF5Validator()
            with pytest.raises(QualityCheckError):
                validator.verify_data(tmp_path)

        finally:
            os.unlink(tmp_path)

    def test_timestamp_jump_detected(self):
        """A timestamp jump in a _timestamp key should be detected."""
        with tempfile.NamedTemporaryFile(
            suffix=".hdf5", prefix="20250101_Test_S1_01_", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            create_synthetic_hdf5(tmp_path, num_frames=50)

            # Inject a timestamp jump into a _timestamp key (validator only
            # checks keys ending with _timestamp, not the "time" key itself)
            with h5py.File(tmp_path, "r+") as f:
                data = f["joints_dict/state_timestamp"][:]
                data[25] = 100.0  # Huge jump from ~0.83 to 100.0
                del f["joints_dict/state_timestamp"]
                f["joints_dict"].create_dataset("state_timestamp", data=data)

            validator = HDF5Validator()
            with pytest.raises(QualityCheckError):
                validator.verify_data(tmp_path)

        finally:
            os.unlink(tmp_path)

    def test_timestamp_duplicate_detected(self):
        """Excessive timestamp duplication in a _timestamp key should be detected."""
        with tempfile.NamedTemporaryFile(
            suffix=".hdf5", prefix="20250101_Test_S1_01_", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            create_synthetic_hdf5(tmp_path, num_frames=50)

            # Inject duplicated timestamps into a _timestamp key
            with h5py.File(tmp_path, "r+") as f:
                data = f["joints_dict/state_timestamp"][:]
                data[5:35] = data[5]  # Same timestamp repeated 30 times (> max_repetition_count=10)
                del f["joints_dict/state_timestamp"]
                f["joints_dict"].create_dataset("state_timestamp", data=data)

            validator = HDF5Validator()
            with pytest.raises(QualityCheckError):
                validator.verify_data(tmp_path)

        finally:
            os.unlink(tmp_path)

    def test_validator_loaded_from_package(self):
        """Smoke check that the package-level API works."""
        from astribot_dq import HDF5Validator, QualityCheckError

        v = HDF5Validator()
        assert v.config is not None
        assert v.config.data_frequency == 30

    def test_config_loads_defaults(self):
        """ValidationConfig should load from YAML with defaults."""
        from astribot_dq.config import load_validation_config_from_yaml

        config = load_validation_config_from_yaml()
        assert config.data_frequency == 30
        assert config.max_repetition_count == 10
        assert config.max_jump_timestamp == 0.2
        assert config.check_config.timestamp.enable is True
        assert config.check_config.timestamp.level == "exception"


class TestInvalidDataDB:
    """Smoke tests for InvalidDataDB."""

    def test_init_and_add_record(self):
        from astribot_dq.invalid_data_db import InvalidDataDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = InvalidDataDB(tmpdir)
            assert os.path.exists(db.db_path)

            record_id = db.add_invalid_record(
                original_path="/fake/original.hdf5",
                invalid_path="/fake/invalid.hdf5",
                error_summary="timestamp repeat too high",
                error_details_list=[{"key_name": "test", "count": 5}],
                error_type="TimestampRepeat",
                task_name="TestTask",
            )
            assert record_id > 0

            record = db.get_record_by_id(record_id)
            assert record is not None
            assert record["file_name"] == "original.hdf5"
            assert record["error_type"] == "TimestampRepeat"

            stats = db.get_statistics()
            assert stats["total_count"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
