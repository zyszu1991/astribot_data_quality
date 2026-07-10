#!/usr/bin/env python3
"""Parse QC log files and generate statistical summaries with histograms.

Usage:
    python3 scripts/log_statistics.py /path/to/logs --bins 100 --date 2025-12-24
"""

import os
import re
import argparse
from enum import Enum
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from collections import defaultdict
import numpy as np


class RobotType(Enum):
    S0 = "S0"
    S1 = "S1"
    S1_u = "S1_u"


def parse_time_string(time_str):
    if not time_str:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: {time_str}")


def extract_log_timestamp(line):
    match = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return None


def parse_task(task_name):
    robot_type_values = "|".join([rt.value for rt in RobotType])
    pattern = (
        rf"^(?P<date>\d{{8}})_(?P<descpition>[A-Za-z0-9_]*)"
        rf"_(?P<robot_type>{robot_type_values})_(?P<robot_id>[0-9]*)"
        rf"_(?P<custom_suffix>[A-Za-z0-9_]*)?$"
    )
    match = re.match(pattern, task_name)
    return match.groupdict() if match else None


def parse_log_file(filepath, task_name=None, robot_id=None, date=None, since=None):
    task_stats = []
    since_datetime = None
    if not filepath.split("/")[-1].startswith("trans"):
        return task_stats
    if since:
        since_datetime = parse_time_string(since)

    with open(filepath, "r", encoding="utf-8") as f:
        current_task = None
        max_repeat_count = 0
        max_adjacent_diff = 0
        max_alignment_diff = 0
        fk_max_pos_errors = []
        fk_mean_pos_errors = []
        fk_max_ori_errors = []
        fk_mean_ori_errors = []
        camera_max_intervals = []
        joints_position_state_normal_diffs = []
        joints_position_state_gripper_diffs = []
        joints_velocity_state_normal_diffs = []
        joints_velocity_state_gripper_diffs = []
        joints_position_command_normal_diffs = []
        joints_position_command_gripper_diffs = []

        for line in f:
            if "Received request to execute task:" in line:
                task = line.split("/")[-1].split("_episode_")[0]
                if task_name and task != task_name:
                    continue
                if robot_id is not None:
                    props = parse_task(task)
                    if not props or int(props.get("robot_id", -1)) != robot_id:
                        continue
                if date is not None and date not in line:
                    continue
                if since_datetime is not None:
                    lt = extract_log_timestamp(line)
                    if lt is None or lt < since_datetime:
                        continue
                current_task = task
                max_repeat_count = max_adjacent_diff = max_alignment_diff = 0
                fk_max_pos_errors = []
                fk_mean_pos_errors = []
                fk_max_ori_errors = []
                fk_mean_ori_errors = []
                camera_max_intervals = []
                joints_position_state_normal_diffs = []
                joints_position_state_gripper_diffs = []
                joints_velocity_state_normal_diffs = []
                joints_velocity_state_gripper_diffs = []
                joints_position_command_normal_diffs = []
                joints_position_command_gripper_diffs = []
            elif task_name and current_task != task_name:
                continue
            elif not current_task:
                continue
            elif "最大重复次数=" in line:
                max_repeat_count = max(max_repeat_count, int(re.search(r"最大重复次数=(\d+)", line).group(1)))
            elif "相邻最大差值:" in line:
                max_adjacent_diff = max(max_adjacent_diff, float(re.search(r"相邻最大差值: ([\d.]+)", line).group(1)))
            elif "时间戳对齐检查的最大差值:" in line:
                max_alignment_diff = max(max_alignment_diff, float(re.search(r"时间戳对齐检查的最大差值: ([\d.]+)", line).group(1)))
            elif " FK结果:" in line and "max_pos_error=" in line:
                m = re.search(r"max_pos_error=([\d.]+).*?mean_pos_error=([\d.]+).*?max_ori_error=([\d.]+).*?mean_ori_error=([\d.]+)", line)
                if m:
                    fk_max_pos_errors.append(float(m.group(1)))
                    fk_mean_pos_errors.append(float(m.group(2)))
                    fk_max_ori_errors.append(float(m.group(3)))
                    fk_mean_ori_errors.append(float(m.group(4)))
            elif "相机" in line and "帧间隔正常:" in line and "最大帧间隔差值" in line:
                m = re.search(r"最大帧间隔差值\s+([\d.]+)", line)
                if m:
                    camera_max_intervals.append(float(m.group(1)))
            elif "[joints_dict/joints_position_state] - 普通关节最大差异:" in line:
                m = re.search(r"差异值=([\d.]+)", line)
                if m:
                    joints_position_state_normal_diffs.append(float(m.group(1)))
            elif "[joints_dict/joints_position_state] - 夹爪最大差异:" in line:
                m = re.search(r"差异值=([\d.]+)", line)
                if m:
                    joints_position_state_gripper_diffs.append(float(m.group(1)))
            elif "[joints_dict/joints_velocity_state] - 普通关节最大差异:" in line:
                m = re.search(r"差异值=([\d.]+)", line)
                if m:
                    joints_velocity_state_normal_diffs.append(float(m.group(1)))
            elif "[joints_dict/joints_velocity_state] - 夹爪最大差异:" in line:
                m = re.search(r"差异值=([\d.]+)", line)
                if m:
                    joints_velocity_state_gripper_diffs.append(float(m.group(1)))
            elif "[joints_dict/joints_position_command] - 普通关节最大差异:" in line:
                m = re.search(r"差异值=([\d.]+)", line)
                if m:
                    joints_position_command_normal_diffs.append(float(m.group(1)))
            elif "[joints_dict/joints_position_command] - 夹爪最大差异:" in line:
                m = re.search(r"差异值=([\d.]+)", line)
                if m:
                    joints_position_command_gripper_diffs.append(float(m.group(1)))
            elif "Process task finished: " in line or "验证文件:" in line:
                if current_task and ("Process task finished: " in line):
                    task_stats.append({
                        "task_name": current_task,
                        "max_repeat_count": max_repeat_count,
                        "max_adjacent_diff": max_adjacent_diff,
                        "max_alignment_diff": max_alignment_diff,
                        "fk_max_pos_errors": fk_max_pos_errors,
                        "fk_mean_pos_errors": fk_mean_pos_errors,
                        "fk_max_ori_errors": fk_max_ori_errors,
                        "fk_mean_ori_errors": fk_mean_ori_errors,
                        "camera_max_intervals": camera_max_intervals,
                        "joints_position_state_normal_diffs": joints_position_state_normal_diffs,
                        "joints_position_state_gripper_diffs": joints_position_state_gripper_diffs,
                        "joints_velocity_state_normal_diffs": joints_velocity_state_normal_diffs,
                        "joints_velocity_state_gripper_diffs": joints_velocity_state_gripper_diffs,
                        "joints_position_command_normal_diffs": joints_position_command_normal_diffs,
                        "joints_position_command_gripper_diffs": joints_position_command_gripper_diffs,
                    })
                    current_task = None
        # last task
        if current_task:
            task_stats.append({
                "task_name": current_task,
                "max_repeat_count": max_repeat_count,
                "max_adjacent_diff": max_adjacent_diff,
                "max_alignment_diff": max_alignment_diff,
                "fk_max_pos_errors": fk_max_pos_errors,
                "fk_mean_pos_errors": fk_mean_pos_errors,
                "fk_max_ori_errors": fk_max_ori_errors,
                "fk_mean_ori_errors": fk_mean_ori_errors,
                "camera_max_intervals": camera_max_intervals,
                "joints_position_state_normal_diffs": joints_position_state_normal_diffs,
                "joints_position_state_gripper_diffs": joints_position_state_gripper_diffs,
                "joints_velocity_state_normal_diffs": joints_velocity_state_normal_diffs,
                "joints_velocity_state_gripper_diffs": joints_velocity_state_gripper_diffs,
                "joints_position_command_normal_diffs": joints_position_command_normal_diffs,
                "joints_position_command_gripper_diffs": joints_position_command_gripper_diffs,
            })
    print(f"Processed log file: {filepath}, {len(task_stats)} tasks found.")
    return task_stats


def aggregate_statistics(folder, task_name=None, robot_id=None, date=None, since=None):
    all_stats = []
    for filename in os.listdir(folder):
        filepath = os.path.join(folder, filename)
        all_stats.extend(parse_log_file(filepath, task_name, robot_id, date, since))
    return all_stats


def calculate_percentile_value(data, percentile):
    if not data:
        return None
    sorted_data = np.sort(data)
    index = int(len(sorted_data) * percentile / 100)
    return sorted_data[min(index, len(sorted_data) - 1)]


def plot_histogram(data, title, xlabel, ylabel, bins, output_file, draw=True):
    if not data:
        return {"type": title, "count": 0, "min": None, "max": None, "mean": None, "p80": None, "p95": None, "p99": None}

    p80 = calculate_percentile_value(data, 80)
    p95 = calculate_percentile_value(data, 95)
    p99 = calculate_percentile_value(data, 99)
    stats = {
        "type": title, "count": len(data), "min": min(data), "max": max(data),
        "mean": np.mean(data), "p80": p80, "p95": p95, "p99": p99,
    }
    print(f"\n{title}: count={len(data)} min={min(data):.4f} max={max(data):.4f} mean={np.mean(data):.4f} p80={p80:.4f} p95={p95:.4f} p99={p99:.4f}")

    if not draw:
        return stats

    plt.figure(figsize=(10, 6))
    weights = [100.0 / len(data)] * len(data)
    counts, bin_edges, patches = plt.hist(data, bins=bins, weights=weights, edgecolor="black", alpha=0.7)
    plt.axvline(p80, color="orange", linestyle="--", linewidth=2, label=f"p80: {p80:.4f}")
    plt.axvline(p95, color="red", linestyle="--", linewidth=2, label=f"p95: {p95:.4f}")
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel + " (%)")
    plt.legend()
    plt.grid(axis="y", linestyle="--", alpha=0.7)
    for count, patch in zip(counts, patches):
        if patch.get_height() > 0:
            plt.text(patch.get_x() + patch.get_width() / 2, patch.get_height(), f"{count:.1f}%", ha="center", va="bottom", fontsize=9)
    step = max(1, len(bin_edges) // (bins // 2 + 1))
    selected_edges = bin_edges[::step]
    plt.xticks(selected_edges, [f"{edge:.2f}" for edge in selected_edges], rotation=45)
    plt.tight_layout()
    plt.savefig(output_file)
    print(f"  Chart saved to: {output_file}")
    plt.close()
    return stats


def generate_markdown_table(stats_list):
    stats_list = [s for s in stats_list if s["count"] > 0]
    if not stats_list:
        return ""
    md = "\n## Data Statistics\n\n"
    md += "| Type | Count | Min | Max | Mean | p80 | p95 | p99 |\n"
    md += "|------|-------|-----|-----|------|-----|-----|-----|\n"
    for s in stats_list:
        def fmt(v):
            return f"{v:.4f}" if v is not None else "N/A"
        md += f"| {s['type']} | {s['count']} | {fmt(s['min'])} | {fmt(s['max'])} | {fmt(s['mean'])} | {fmt(s['p80'])} | {fmt(s['p95'])} | {fmt(s['p99'])} |\n"
    return md


def main():
    parser = argparse.ArgumentParser(description="Analyze QC log files.")
    parser.add_argument("folder", help="Path to log folder")
    parser.add_argument("--task_name", type=str, default=None)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--output", default="output")
    parser.add_argument("--robot_id", type=int, default=None)
    parser.add_argument("--diff_threshold", type=float, default=None)
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--since", type=str, default=None)
    parser.add_argument("--draw", type=str, default="true")
    args = parser.parse_args()

    draw = args.draw.lower() in ("true", "1", "yes")
    os.makedirs(args.output, exist_ok=True)

    stats = aggregate_statistics(args.folder, args.task_name, args.robot_id, args.date, args.since)
    if not stats:
        print("No data found!")
        return

    max_repeat_counts = [s["max_repeat_count"] for s in stats]
    max_adjacent_diffs = [s["max_adjacent_diff"] for s in stats]
    max_alignment_diffs = [s["max_alignment_diff"] for s in stats]

    all_fk_max_pos = []; all_fk_mean_pos = []; all_fk_max_ori = []; all_fk_mean_ori = []
    all_camera_max = []
    all_jps_normal = []; all_jps_gripper = []
    all_jvs_normal = []; all_jvs_gripper = []
    all_jpc_normal = []; all_jpc_gripper = []

    for s in stats:
        all_fk_max_pos.extend(s["fk_max_pos_errors"]); all_fk_mean_pos.extend(s["fk_mean_pos_errors"])
        all_fk_max_ori.extend(s["fk_max_ori_errors"]); all_fk_mean_ori.extend(s["fk_mean_ori_errors"])
        all_camera_max.extend(s["camera_max_intervals"])
        all_jps_normal.extend(s["joints_position_state_normal_diffs"]); all_jps_gripper.extend(s["joints_position_state_gripper_diffs"])
        all_jvs_normal.extend(s["joints_velocity_state_normal_diffs"]); all_jvs_gripper.extend(s["joints_velocity_state_gripper_diffs"])
        all_jpc_normal.extend(s["joints_position_command_normal_diffs"]); all_jpc_gripper.extend(s["joints_position_command_gripper_diffs"])

    print(f"\n========= Total: {len(stats)} tasks =========")

    all_stats_list = []
    all_stats_list.append(plot_histogram(max_repeat_counts, "Max Repeat Counts", "Max Repeat Count", "Freq", args.bins, os.path.join(args.output, "max_repeat_counts.png"), draw))
    all_stats_list.append(plot_histogram(max_adjacent_diffs, "Max Adjacent Diffs", "Max Adjacent Diff", "Freq", args.bins, os.path.join(args.output, "max_adjacent_diffs.png"), draw))
    all_stats_list.append(plot_histogram(max_alignment_diffs, "Max Alignment Diffs", "Max Alignment Diff", "Freq", args.bins, os.path.join(args.output, "max_alignment_diffs.png"), draw))

    print(f"\n========= FK Stats =========")
    all_stats_list.append(plot_histogram(all_fk_max_pos, "FK Max Position Error", "Max Pos Error", "Freq", args.bins, os.path.join(args.output, "fk_max_pos_errors.png"), draw))
    all_stats_list.append(plot_histogram(all_fk_mean_pos, "FK Mean Position Error", "Mean Pos Error", "Freq", args.bins, os.path.join(args.output, "fk_mean_pos_errors.png"), draw))
    all_stats_list.append(plot_histogram(all_fk_max_ori, "FK Max Orientation Error", "Max Ori Error", "Freq", args.bins, os.path.join(args.output, "fk_max_ori_errors.png"), draw))
    all_stats_list.append(plot_histogram(all_fk_mean_ori, "FK Mean Orientation Error", "Mean Ori Error", "Freq", args.bins, os.path.join(args.output, "fk_mean_ori_errors.png"), draw))

    print(f"\n========= Camera Frame Interval =========")
    all_stats_list.append(plot_histogram(all_camera_max, "Camera Max Frame Interval", "Max Interval", "Freq", args.bins, os.path.join(args.output, "camera_max_intervals.png"), draw))

    print(f"\n========= Joints Position State =========")
    all_stats_list.append(plot_histogram(all_jps_normal, "Joints Position State Normal", "Max Diff", "Freq", args.bins, os.path.join(args.output, "jps_normal.png"), draw))
    all_stats_list.append(plot_histogram(all_jps_gripper, "Joints Position State Gripper", "Max Diff", "Freq", args.bins, os.path.join(args.output, "jps_gripper.png"), draw))

    print(f"\n========= Joints Velocity State =========")
    all_stats_list.append(plot_histogram(all_jvs_normal, "Joints Velocity State Normal", "Max Diff", "Freq", args.bins, os.path.join(args.output, "jvs_normal.png"), draw))
    all_stats_list.append(plot_histogram(all_jvs_gripper, "Joints Velocity State Gripper", "Max Diff", "Freq", args.bins, os.path.join(args.output, "jvs_gripper.png"), draw))

    print(f"\n========= Joints Position Command =========")
    all_stats_list.append(plot_histogram(all_jpc_normal, "Joints Position Command Normal", "Max Diff", "Freq", args.bins, os.path.join(args.output, "jpc_normal.png"), draw))
    all_stats_list.append(plot_histogram(all_jpc_gripper, "Joints Position Command Gripper", "Max Diff", "Freq", args.bins, os.path.join(args.output, "jpc_gripper.png"), draw))

    if args.diff_threshold is not None:
        exceeding = [s for s in stats if s["max_adjacent_diff"] > args.diff_threshold]
        print(f"\nAdjacent diffs exceeding {args.diff_threshold}: {len(exceeding)}/{len(stats)} ({len(exceeding)/len(stats)*100:.2f}%)")

    md = generate_markdown_table(all_stats_list)
    if md:
        print(md)

    print(f"\nHistograms saved to {args.output}")


if __name__ == "__main__":
    main()
