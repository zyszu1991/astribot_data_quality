import os
import re
from typing import Optional

from astribot_dq.constant import TRANS_PREFIX
from astribot_dq.schemas import RobotType


class FilePath:
    @classmethod
    def get_robot_type_from_task(cls, task_name: str) -> Optional[RobotType]:
        target_name = task_name.replace(TRANS_PREFIX, "").split(".")[0]
        robot_type_values = "|".join([rt.value for rt in RobotType])
        pattern = (
            rf".*_(?P<robot_type>{robot_type_values})_(?P<custom_suffix>[A-Za-z0-9_]*)?$"
        )
        match = re.match(pattern, target_name)
        if match:
            robot_type_str = match.group("robot_type")
            return RobotType(robot_type_str)
        return None

    @classmethod
    def remove_empty_dirs(cls, dir_path: str, root_dir: str):
        while True:
            if not os.path.exists(dir_path):
                break
            if dir_path == root_dir:
                return
            if os.path.isdir(dir_path) and not os.listdir(dir_path):
                os.rmdir(dir_path)
                dir_path = os.path.dirname(dir_path)
            else:
                break
