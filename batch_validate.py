#!/usr/bin/env python3
"""批量 HDF5 数据质检工具 - 支持并行处理和详细报告导出

使用方法:
    python batch_validate.py --input /path/to/dataset --output report.json
    python batch_validate.py --input /path/to/dataset --output report.json --workers 4
    python batch_validate.py --input /path/to/dataset --output report.json --csv report.csv
"""

import argparse
import json
import csv
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

from astribot_dq.validator import HDF5Validator
from astribot_dq.schemas import QualityCheckError
from astribot_dq.logger import g_logger


def find_hdf5_files(root_dir: str) -> List[str]:
    """递归查找所有 HDF5 文件"""
    hdf5_files = []
    for ext in ['*.hdf5', '*.h5']:
        hdf5_files.extend(Path(root_dir).rglob(ext))
    return [str(f) for f in sorted(hdf5_files)]


def validate_single_file(file_path: str, config_path: str = None, disable_fk: bool = False) -> Dict[str, Any]:
    """验证单个 HDF5 文件"""
    start_time = time.time()
    result = {
        'file_path': file_path,
        'file_name': os.path.basename(file_path),
        'file_size_mb': os.path.getsize(file_path) / (1024 * 1024),
        'status': 'unknown',
        'error_type': None,
        'error_summary': None,
        'error_details': None,
        'validation_time_s': 0,
        'timestamp': datetime.now().isoformat(),
    }

    try:
        validator = HDF5Validator(config_path)
        if disable_fk:
            validator.config.check_config.forward_kinematics.enable = False

        validator.verify_data(file_path)
        result['status'] = 'PASS'

    except QualityCheckError as e:
        result['status'] = 'FAIL'
        result['error_type'] = e.error_type
        result['error_summary'] = e.error_summary
        result['error_details'] = e.error_details_list

    except Exception as e:
        result['status'] = 'ERROR'
        result['error_type'] = type(e).__name__
        result['error_summary'] = str(e)

    finally:
        result['validation_time_s'] = round(time.time() - start_time, 3)

    return result


def batch_validate(
    input_dir: str,
    output_json: str,
    output_csv: str = None,
    config_path: str = None,
    workers: int = 1,
    disable_fk: bool = False,
) -> Dict[str, Any]:
    """批量验证 HDF5 文件并生成报告"""

    print("=" * 80)
    print("Astribot 数据质检批量工具")
    print("=" * 80)

    # 查找文件
    print(f"\n[1/4] 扫描目录: {input_dir}")
    hdf5_files = find_hdf5_files(input_dir)
    print(f"找到 {len(hdf5_files)} 个 HDF5 文件")

    if len(hdf5_files) == 0:
        print("❌ 未找到任何 HDF5 文件")
        return None

    # 并行验证
    print(f"\n[2/4] 开始验证（{workers} 个并行进程）...")
    results = []

    if workers == 1:
        # 单进程模式，显示进度
        for i, file_path in enumerate(hdf5_files, 1):
            print(f"  [{i}/{len(hdf5_files)}] {os.path.basename(file_path)}...", end=' ')
            result = validate_single_file(file_path, config_path, disable_fk)
            status_icon = "✅" if result['status'] == 'PASS' else "❌"
            print(f"{status_icon} {result['status']} ({result['validation_time_s']}s)")
            results.append(result)
    else:
        # 多进程模式
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_file = {
                executor.submit(validate_single_file, f, config_path, disable_fk): f
                for f in hdf5_files
            }

            completed = 0
            for future in as_completed(future_to_file):
                completed += 1
                file_path = future_to_file[future]
                try:
                    result = future.result()
                    results.append(result)
                    status_icon = "✅" if result['status'] == 'PASS' else "❌"
                    print(f"  [{completed}/{len(hdf5_files)}] {os.path.basename(file_path)} {status_icon} {result['status']}")
                except Exception as e:
                    print(f"  [{completed}/{len(hdf5_files)}] {os.path.basename(file_path)} ❌ CRASH: {e}")

    # 统计
    print(f"\n[3/4] 生成统计报告...")
    summary = generate_summary(results)

    # 导出
    print(f"\n[4/4] 导出报告...")
    report = {
        'summary': summary,
        'results': results,
        'metadata': {
            'input_dir': input_dir,
            'total_files': len(hdf5_files),
            'config_path': config_path,
            'workers': workers,
            'disable_fk': disable_fk,
            'generated_at': datetime.now().isoformat(),
        }
    }

    # 导出 JSON
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  ✅ JSON 报告: {output_json}")

    # 导出 CSV（可选）
    if output_csv:
        export_csv(results, output_csv)
        print(f"  ✅ CSV 报告: {output_csv}")

    # 打印摘要
    print("\n" + "=" * 80)
    print("验证摘要")
    print("=" * 80)
    print(f"总文件数:       {summary['total_files']}")
    print(f"通过:          {summary['passed']} ({summary['pass_rate']:.1f}%)")
    print(f"失败:          {summary['failed']} ({summary['fail_rate']:.1f}%)")
    print(f"错误:          {summary['errors']}")
    print(f"总耗时:        {summary['total_time_s']:.2f}s")
    print(f"平均耗时:      {summary['avg_time_s']:.3f}s/文件")

    if summary['failed'] > 0:
        print(f"\n失败类型分布:")
        for error_type, count in summary['error_types'].items():
            print(f"  - {error_type}: {count}")

    print("=" * 80)

    return report


def generate_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """生成统计摘要"""
    total = len(results)
    passed = sum(1 for r in results if r['status'] == 'PASS')
    failed = sum(1 for r in results if r['status'] == 'FAIL')
    errors = sum(1 for r in results if r['status'] == 'ERROR')

    error_types = {}
    for r in results:
        if r['status'] == 'FAIL' and r['error_type']:
            error_types[r['error_type']] = error_types.get(r['error_type'], 0) + 1

    total_time = sum(r['validation_time_s'] for r in results)
    avg_time = total_time / total if total > 0 else 0

    return {
        'total_files': total,
        'passed': passed,
        'failed': failed,
        'errors': errors,
        'pass_rate': (passed / total * 100) if total > 0 else 0,
        'fail_rate': (failed / total * 100) if total > 0 else 0,
        'error_types': error_types,
        'total_time_s': round(total_time, 2),
        'avg_time_s': round(avg_time, 3),
    }


def export_csv(results: List[Dict[str, Any]], output_csv: str):
    """导出为 CSV 格式"""
    if not results:
        return

    fieldnames = [
        'file_name', 'status', 'error_type', 'error_summary',
        'file_size_mb', 'validation_time_s', 'timestamp'
    ]

    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in results:
            row = {k: r.get(k, '') for k in fieldnames}
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(
        description='批量 HDF5 数据质检工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基础用法
  python batch_validate.py --input /path/to/dataset --output report.json

  # 并行处理（4个进程）
  python batch_validate.py --input /path/to/dataset --output report.json --workers 4

  # 同时导出 CSV
  python batch_validate.py --input /path/to/dataset --output report.json --csv report.csv

  # 使用自定义配置
  python batch_validate.py --input /path/to/dataset --output report.json --config my_config.yaml

  # 禁用 FK 检查（无 API 环境）
  python batch_validate.py --input /path/to/dataset --output report.json --disable-fk
        """
    )

    parser.add_argument(
        '--input', '-i',
        required=True,
        help='输入目录（包含 HDF5 文件）'
    )
    parser.add_argument(
        '--output', '-o',
        required=True,
        help='输出 JSON 报告路径'
    )
    parser.add_argument(
        '--csv', '-c',
        help='可选：同时导出 CSV 报告路径'
    )
    parser.add_argument(
        '--config',
        help='可选：自定义质检配置 YAML 文件路径'
    )
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=1,
        help='并行进程数（默认: 1）'
    )
    parser.add_argument(
        '--disable-fk',
        action='store_true',
        help='禁用 FK 检查（无 API 环境时使用）'
    )

    args = parser.parse_args()

    # 验证输入目录
    if not os.path.isdir(args.input):
        print(f"❌ 错误: 输入目录不存在: {args.input}")
        sys.exit(1)

    # 创建输出目录
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # 运行批量验证
    try:
        report = batch_validate(
            input_dir=args.input,
            output_json=args.output,
            output_csv=args.csv,
            config_path=args.config,
            workers=args.workers,
            disable_fk=args.disable_fk,
        )

        if report:
            # 返回非零退出码如果有失败
            if report['summary']['failed'] > 0 or report['summary']['errors'] > 0:
                sys.exit(1)
        else:
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ 批量验证失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
