import dataclasses
from enum import Enum
from typing import Optional


class RobotType(Enum):
    S0 = "S0"
    S1 = "S1"
    S1_u = "S1_u"


@dataclasses.dataclass
class TaskInfo:
    date: str
    main_task: str
    sub_task: Optional[str]
    robot_type: RobotType
    custom_suffix: Optional[str]


def dataclass_from_dict(klass, d):
    try:
        fieldtypes = {f.name: f.type for f in dataclasses.fields(klass)}
        return klass(**{f: dataclass_from_dict(fieldtypes[f], d[f]) for f in d})
    except Exception:
        return d


class QualityCheckError(Exception):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._error_type = cls.__name__

    def __init__(self, message, error_summary, error_details_list):
        super().__init__(message)
        self.error_summary = error_summary
        self.error_details_list = error_details_list
        self.error_type = self._error_type


class TimestampEmpty(QualityCheckError):
    pass


class TimestampRepeat(QualityCheckError):
    pass


class TimestampMismatch(QualityCheckError):
    pass


class TimestampJump(QualityCheckError):
    pass


class TimestampInvalidDuration(QualityCheckError):
    pass


class KeyNotFound(QualityCheckError):
    pass


class KeyInvalid(QualityCheckError):
    pass


class KeySizeIncorrect(QualityCheckError):
    pass


class CartesianJointFKMismatch(QualityCheckError):
    pass


class CameraFrameDiffInvalid(QualityCheckError):
    pass


class JointStateFrameDiffInvalid(QualityCheckError):
    pass


class JointCmdFrameDiffInvalid(QualityCheckError):
    pass


class CartesianStateFrameDiffInvalid(QualityCheckError):
    pass


class CartesianCmdFrameDiffInvalid(QualityCheckError):
    pass
