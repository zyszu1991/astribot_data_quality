# 批量质检使用指南

## 快速开始

### 1. 基础用法

```bash
cd /Users/gabrizhao/Documents/projects/repos/astribot_data_quality

# 验证 dataset 目录中的所有 HDF5 文件
python batch_validate.py \
    --input /Users/gabrizhao/Documents/projects/dataset \
    --output quality_report.json \
    --disable-fk
```

### 2. 并行处理（推荐）

利用多核 CPU 加速验证：

```bash
# 使用 4 个进程并行验证
python batch_validate.py \
    --input /Users/gabrizhao/Documents/projects/dataset \
    --output quality_report.json \
    --workers 4 \
    --disable-fk
```

### 3. 导出 CSV 报告

同时生成 JSON 和 CSV 两种格式：

```bash
python batch_validate.py \
    --input /Users/gabrizhao/Documents/projects/dataset \
    --output quality_report.json \
    --csv quality_report.csv \
    --workers 4 \
    --disable-fk
```

### 4. 使用自定义配置

```bash
python batch_validate.py \
    --input /Users/gabrizhao/Documents/projects/dataset \
    --output quality_report.json \
    --config custom_config.yaml \
    --workers 4
```

---

## 输出报告格式

### JSON 报告结构

```json
{
  "summary": {
    "total_files": 100,
    "passed": 85,
    "failed": 12,
    "errors": 3,
    "pass_rate": 85.0,
    "fail_rate": 12.0,
    "error_types": {
      "CommandPoseZeroSegment": 8,
      "TimestampJump": 3,
      "TimestampMismatch": 1
    },
    "total_time_s": 45.23,
    "avg_time_s": 0.452
  },
  "results": [
    {
      "file_path": "/path/to/episode_0.hdf5",
      "file_name": "episode_0.hdf5",
      "file_size_mb": 125.4,
      "status": "FAIL",
      "error_type": "CommandPoseZeroSegment",
      "error_summary": "Command pose zero/constant segments detected: ['astribot_chassis']",
      "error_details": [...],
      "validation_time_s": 0.523,
      "timestamp": "2026-07-14T18:00:00"
    },
    ...
  ],
  "metadata": {
    "input_dir": "/path/to/dataset",
    "total_files": 100,
    "config_path": null,
    "workers": 4,
    "disable_fk": true,
    "generated_at": "2026-07-14T18:00:00"
  }
}
```

### CSV 报告字段

| 字段 | 说明 |
|------|------|
| `file_name` | 文件名 |
| `status` | PASS / FAIL / ERROR |
| `error_type` | 错误类型（如 CommandPoseZeroSegment） |
| `error_summary` | 错误摘要 |
| `file_size_mb` | 文件大小（MB） |
| `validation_time_s` | 验证耗时（秒） |
| `timestamp` | 验证时间戳 |

---

## 报告分析

### 1. Python 分析脚本

```python
import json
import pandas as pd

# 读取 JSON 报告
with open('quality_report.json', 'r') as f:
    report = json.load(f)

# 提取摘要
summary = report['summary']
print(f"通过率: {summary['pass_rate']:.1f}%")
print(f"失败数: {summary['failed']}")

# 失败类型分析
for error_type, count in summary['error_types'].items():
    print(f"  - {error_type}: {count}")

# 查找失败的文件
failed_files = [
    r for r in report['results'] 
    if r['status'] == 'FAIL'
]

for f in failed_files:
    print(f"{f['file_name']}: {f['error_type']}")
```

### 2. 使用 Pandas 分析 CSV

```python
import pandas as pd

# 读取 CSV
df = pd.read_csv('quality_report.csv')

# 统计各状态数量
print(df['status'].value_counts())

# 失败类型分布
print(df[df['status'] == 'FAIL']['error_type'].value_counts())

# 按文件大小分析
df['size_category'] = pd.cut(df['file_size_mb'], bins=[0, 50, 100, 200, 500])
print(df.groupby('size_category')['status'].value_counts())

# 导出失败文件列表
failed = df[df['status'] == 'FAIL'][['file_name', 'error_type', 'error_summary']]
failed.to_csv('failed_files.csv', index=False)
```

### 3. 生成可视化报告

```python
import json
import matplotlib.pyplot as plt

with open('quality_report.json', 'r') as f:
    report = json.load(f)

summary = report['summary']

# 饼图 - 状态分布
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

ax1.pie(
    [summary['passed'], summary['failed'], summary['errors']],
    labels=['通过', '失败', '错误'],
    autopct='%1.1f%%',
    colors=['#2ecc71', '#e74c3c', '#f39c12']
)
ax1.set_title('数据质检结果分布')

# 柱状图 - 错误类型
error_types = summary['error_types']
ax2.bar(error_types.keys(), error_types.values())
ax2.set_xlabel('错误类型')
ax2.set_ylabel('数量')
ax2.set_title('失败类型分布')
plt.xticks(rotation=45, ha='right')

plt.tight_layout()
plt.savefig('quality_report.png', dpi=300, bbox_inches='tight')
print("✅ 可视化报告已保存: quality_report.png")
```

---

## 常见问题

### Q1: 如何只验证特定错误类型？

修改 `config/validation_config.yaml`：

```yaml
check_config:
  timestamp:
    enable: true
    level: "exception"
  forward_kinematics:
    enable: false  # 禁用 FK 检查
  frame_difference:
    enable: true
    level: "warning"
```

### Q2: 如何处理大数据集（10000+ 文件）？

1. **增加并行度**：
```bash
python batch_validate.py \
    --input /large/dataset \
    --output report.json \
    --workers 8  # 使用 8 个进程
```

2. **分批处理**：
```bash
# 分目录处理
for dir in /large/dataset/*/; do
    python batch_validate.py \
        --input "$dir" \
        --output "report_$(basename $dir).json" \
        --workers 4
done
```

### Q3: 如何集成到 CI/CD 流程？

```bash
#!/bin/bash
# ci_check.sh

python batch_validate.py \
    --input /data/new_episodes \
    --output ci_report.json \
    --workers 4 \
    --disable-fk

# 检查退出码（失败时返回非零）
if [ $? -ne 0 ]; then
    echo "❌ 数据质检失败"
    # 发送告警、停止流程等
    exit 1
fi

echo "✅ 数据质检通过"
```

### Q4: 如何生成 HTML 报告？

```python
# generate_html_report.py
import json
from datetime import datetime

with open('quality_report.json', 'r') as f:
    report = json.load(f)

summary = report['summary']

html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>数据质检报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .summary {{ background: #f5f5f5; padding: 20px; border-radius: 8px; }}
        .pass {{ color: #2ecc71; }}
        .fail {{ color: #e74c3c; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #3498db; color: white; }}
    </style>
</head>
<body>
    <h1>Astribot 数据质检报告</h1>
    <div class="summary">
        <h2>摘要</h2>
        <p>总文件数: {summary['total_files']}</p>
        <p class="pass">通过: {summary['passed']} ({summary['pass_rate']:.1f}%)</p>
        <p class="fail">失败: {summary['failed']} ({summary['fail_rate']:.1f}%)</p>
        <p>总耗时: {summary['total_time_s']:.2f}s</p>
    </div>
    
    <h2>失败类型分布</h2>
    <ul>
"""

for error_type, count in summary['error_types'].items():
    html += f"<li>{error_type}: {count}</li>"

html += """
    </ul>
    
    <h2>详细结果</h2>
    <table>
        <tr>
            <th>文件名</th>
            <th>状态</th>
            <th>错误类型</th>
            <th>文件大小(MB)</th>
            <th>耗时(s)</th>
        </tr>
"""

for r in report['results']:
    status_class = 'pass' if r['status'] == 'PASS' else 'fail'
    html += f"""
        <tr>
            <td>{r['file_name']}</td>
            <td class="{status_class}">{r['status']}</td>
            <td>{r.get('error_type', '-')}</td>
            <td>{r['file_size_mb']:.2f}</td>
            <td>{r['validation_time_s']:.3f}</td>
        </tr>
    """

html += """
    </table>
    <p style="margin-top: 40px; color: #888;">
        生成时间: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """
    </p>
</body>
</html>
"""

with open('quality_report.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("✅ HTML 报告已生成: quality_report.html")
```

---

## 性能参考

| 数据集大小 | 文件数 | 单进程耗时 | 4进程耗时 | 加速比 |
|-----------|--------|-----------|----------|--------|
| 小型 | 100 | ~45s | ~15s | 3x |
| 中型 | 1,000 | ~7.5min | ~2.5min | 3x |
| 大型 | 10,000 | ~75min | ~25min | 3x |

**注**: 实际性能取决于 HDF5 文件大小、硬件配置、磁盘 I/O 速度等因素。

---

## 技术支持

遇到问题？
1. 检查 `batch_validate.py --help` 查看完整参数说明
2. 查看详细错误日志（默认输出到 stdout）
3. 提交 issue 到 GitLab/GitHub 仓库
