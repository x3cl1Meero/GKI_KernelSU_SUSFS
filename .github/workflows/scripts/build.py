#!/usr/bin/env python3

import argparse

import os

import sys

import json

import logging

import subprocess

import re

from pathlib import Path

from datetime import datetime, timezone


# =========================================================================

# АВТОМАТИЧЕСКИЙ ПЕРЕХВАТ И ИСПРАВЛЕНИЕ СКРЫТЫХ ЗАВИСИМОСТЕЙ ЯДРА (ZRAM / BBR)

# =========================================================================

_orig_Popen = subprocess.Popen

_orig_system = os.system


def _modify_command_str(cmd_str):

    if "scripts/config" in cmd_str:

        extra = ""

        # Если включается BBR, принудительно добавляем сетевой планировщик FQ

        if "DEFAULT_BBR" in cmd_str or "bbr" in cmd_str:

            if "NET_SCH_FQ" not in cmd_str:

                extra += " && {prefix}scripts/config -e NET_SCH_FQ -e TCP_CONG_BBR -e DEFAULT_BBR --set-str DEFAULT_TCP_CONG \"bbr\""

        # Если включается ZRAM, принудительно добавляем LZ4KDC (LZ4 Kernel Decompression + Crypto)

        if "ZRAM" in cmd_str or "lz4" in cmd_str:

            if "CRYPTO_LZ4" not in cmd_str:

                extra += " && {prefix}scripts/config -e CRYPTO_LZ4 -e CRYPTO_LZ4HC -e LZ4_COMPRESS -e LZ4_DECOMPRESS -e ZLIB_DEFLATE -e ZLIB_INFLATE --set-str ZRAM_DEF_COMP \"lz4hc\""

        

        if extra:

            match = re.search(r'(\S*scripts/config)', cmd_str)

            if match:

                prefix = match.group(1).replace("scripts/config", "")

                cmd_str += extra.format(prefix=prefix)

    return cmd_str


def hooked_Popen(args, *vargs, **kwargs):

    if isinstance(args, str):

        args = _modify_command_str(args)

    elif isinstance(args, list):

        if kwargs.get('shell'):

            args = [_modify_command_str(a) if isinstance(a, str) else a for a in args]

        elif len(args) > 0 and isinstance(args[0], str) and "scripts/config" in args[0]:

            cmd_str = " ".join([f'"{a}"' if " " in a else a for a in args])

            cmd_str = _modify_command_str(cmd_str)

            kwargs['shell'] = True

            args = cmd_str

    return _orig_Popen(args, *vargs, **kwargs)


def hooked_system(cmd):

    if isinstance(cmd, str):

        cmd = _modify_command_str(cmd)

    return _orig_system(cmd)


subprocess.Popen = hooked_Popen

os.system = hooked_system

# =========================================================================


sys.path.insert(0, str(Path(__file__).parent))


from config import BuildConfig, AndroidVersion, KernelVersion, ANDROID_KERNEL_MAP, KSUVersion

from kernel_builder import KernelBuilder, BuildResult


logging.basicConfig(

    level=logging.INFO,

    format='\033[92m[%(levelname)s]\033[0m %(message)s',

    datefmt='%Y-%m-%d %H:%M:%S'

)

logger = logging.getLogger(__name__)


DEFAULT_BUILD_MATRIX = {

    "android12-5.10": [

        {"sub_level": "136", "os_patch_level": "2022-11", "revision": "r15"},

        {"sub_level": "198", "os_patch_level": "2024-01", "revision": "r17"},

        {"sub_level": "209", "os_patch_level": "2024-05", "revision": "r13"},

        {"sub_level": "236", "os_patch_level": "2025-05", "revision": "r1"},

        {"sub_level": "X", "os_patch_level": "lts", "revision": "r1"},

    ],

    "android13-5.15": [

        {"sub_level": "74", "os_patch_level": "2023-01"},

        {"sub_level": "123", "os_patch_level": "2023-11"},

        {"sub_level": "148", "os_patch_level": "2024-05"},

        {"sub_level": "167", "os_patch_level": "2024-12"},

        {"sub_level": "170", "os_patch_level": "2025-01"},

        {"sub_level": "178", "os_patch_level": "2025-03"},

        {"sub_level": "180", "os_patch_level": "2025-05"},

        {"sub_level": "189", "os_patch_level": "2025-09"},

    ],

    "android14-6.1": [

        {"sub_level": "78", "os_patch_level": "2024-06"},

        {"sub_level": "90", "os_patch_level": "2024-08"},

        {"sub_level": "99", "os_patch_level": "2024-10"},

        {"sub_level": "124", "os_patch_level": "2025-02"},

        {"sub_level": "138", "os_patch_level": "2025-06"},

        {"sub_level": "145", "os_patch_level": "2025-09"},

    ],

    "android15-6.6": [

        {"sub_level": "50", "os_patch_level": "2024-10"},

        {"sub_level": "66", "os_patch_level": "2025-02"},

        {"sub_level": "102", "os_patch_level": "2025-10"},

    ],

}



def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(description="GKI Kernel 构建系统")


    parser.add_argument("--android", "-a", choices=[v.value for v in AndroidVersion])

    parser.add_argument("--kernel", "-k", choices=[v.value for v in KernelVersion])

    parser.add_argument("--sub-level", "-s")

    parser.add_argument("--os-patch")

    parser.add_argument("--ksu-version", choices=[v.value for v in KSUVersion], default=KSUVersion.STABLE.value)

    parser.add_argument("--ksu-commit", default=None)

    parser.add_argument("--susfs-commit", default=None)

    parser.add_argument("--zram", action="store_true")

    parser.add_argument("--no-kpm", action="store_true")

    parser.add_argument("--bbg", action="store_true")

    parser.add_argument("--op8e", action="store_true")

    parser.add_argument("--bbr", action="store_true")

    parser.add_argument("--no-release", action="store_true")

    parser.add_argument("--custom-version", dest="custom_version", default=None)

    parser.add_argument("--revision")

    parser.add_argument("--matrix", "-m")

    parser.add_argument("--all", action="store_true")

    parser.add_argument("--list-configs", action="store_true")

    parser.add_argument("--list-matrix", action="store_true")

    parser.add_argument("--workspace", "-w", default=os.environ.get("GKI_WORKSPACE", "/tmp/gki-build"))

    parser.add_argument("--verbose", "-v", action="store_true")

    parser.add_argument("--output-json")

    parser.add_argument("--dry-run", action="store_true")

    

    # === НОВЫЙ АРГУМЕНТ ДЛЯ ДАТЫ СОЗДАНИЯ (BUILD_TIME) ===

    parser.add_argument("--build-time", dest="build_time", 

                        help="自定义构建时间 / Custom build time (例如 'Sun Dec 01 08:10:00 UTC 2024' 或 'N' 使用当前时间)")


    return parser.parse_args()



def create_build_config(args: argparse.Namespace) -> BuildConfig:

    return BuildConfig(

        android_version=args.android or "android14",

        kernel_version=args.kernel or "6.1",

        sub_level=args.sub_level or "124",

        os_patch_level=args.os_patch or "2025-02",

        kernelsu_version=args.ksu_version,

        kernelsu_commit=args.ksu_commit,

        susfs_commit=args.susfs_commit,

        use_zram=args.zram,

        use_kpm=not args.no_kpm,

        use_bbg=args.bbg,

        support_op8e=args.op8e,

        set_default_bbr=args.bbr,

        make_release=not args.no_release,

        custom_version=args.custom_version,

        revision=args.revision,

    )



def list_configs():

    print("\n" + "=" * 60)

    print("支持的 Android/Kernel 版本组合")

    print("=" * 60)

    for android, kernels in ANDROID_KERNEL_MAP.items():

        print(f"\n{android.value}:")

        for kernel in kernels:

            configs = DEFAULT_BUILD_MATRIX.get(f"{android.value}-{kernel.value}", [])

            print(f"  - {kernel.value}: {', '.join(c['sub_level'] for c in configs) or 'N/A'}")

    print("\n" + "=" * 60)

    print("KernelSU 版本选项")

    print("=" * 60)

    for v in KSUVersion:

        print(f"  - {v.value}")



def list_matrix():

    print("\n" + "=" * 60)

    print("预定义构建矩阵")

    print("=" * 60)

    for combo, configs in sorted(DEFAULT_BUILD_MATRIX.items()):

        print(f"\n{combo}:")

        for cfg in configs:

            rev = f" (rev: {cfg.get('revision', 'N/A')})" if cfg.get('revision') else ""

            print(f"  - {cfg['sub_level']:>4} | {cfg['os_patch_level']}{rev}")



def build_single(config: BuildConfig, workspace: str, dry_run: bool = False) -> BuildResult:

    if dry_run:

        logger.info(f"[DRY RUN] 验证配置: {config.config_name}")

        return BuildResult(success=True, config=config, message="配置验证通过")


    builder = KernelBuilder(config, workspace)

    return builder.build()



def build_matrix(matrix_key: str, args: argparse.Namespace, workspace: str) -> list:

    logger.info(f"\n{'=' * 60}\n开始构建矩阵: {matrix_key}\n{'=' * 60}\n")


    configs_data = DEFAULT_BUILD_MATRIX.get(matrix_key, [])

    if not configs_data:

        logger.error(f"未知的矩阵: {matrix_key}")

        return []


    results = []

    for cfg_data in configs_data:

        try:

            config = BuildConfig(

                android_version=matrix_key.split("-")[0],

                kernel_version=matrix_key.split("-")[1],

                sub_level=cfg_data["sub_level"],

                os_patch_level=cfg_data["os_patch_level"],

                kernelsu_version=args.ksu_version,

                kernelsu_commit=args.ksu_commit,

                use_zram=args.zram,

                use_kpm=not args.no_kpm,

                use_bbg=args.bbg,

                support_op8e=args.op8e,

                set_default_bbr=args.bbr,

                make_release=not args.no_release,

                custom_version=args.custom_version,

                revision=cfg_data.get("revision"),

            )


            logger.info(f"\n{'=' * 60}\n构建配置: {config.config_name}\n{'=' * 60}")

            result = build_single(config, workspace, args.dry_run)

            results.append(result)


            if result.success:

                logger.info(f"✓ {config.config_name} 构建成功")

            else:

                logger.error(f"✗ {config.config_name} 构建失败: {result.message}")

        except Exception as e:

            logger.error(f"配置 {cfg_data} 出错: {e}")

            continue


    return results



def build_all(args: argparse.Namespace, workspace: str) -> list:

    all_results = []

    for matrix_key in sorted(DEFAULT_BUILD_MATRIX.keys()):

        results = build_matrix(matrix_key, args, workspace)

        all_results.extend(results)

    return all_results



def print_summary(results: list, output_json: str = None):

    total = len(results)

    success = sum(1 for r in results if r.success)


    print("\n" + "=" * 60)

    print("构建摘要")

    print("=" * 60)

    print(f"总数: {total}")

    print(f"成功: \033[92m{success}\033[0m")

    print(f"失败: \033[91m{total - success}\033[0m")


    if success > 0:

        avg_time = sum(r.build_time or 0 for r in results if r.success) / success

        print(f"平均构建时间: {avg_time:.2f} 秒")


    failed = total - success

    if failed > 0:

        print("\n失败的配置:")

        for r in results:

            if not r.success:

                print(f"  - {r.config.config_name}: {r.message}")

    print("=" * 60)


    if output_json:

        json_data = {

            "timestamp": datetime.now().isoformat(),

            "total": total,

            "success": success,

            "failed": failed,

            "results": [{"config": r.config.to_dict(), "success": r.success, "message": r.message,

                       "artifacts": r.artifacts, "build_time": r.build_time} for r in results]

        }

        with open(output_json, "w", encoding="utf-8") as f:

            json.dump(json_data, f, indent=2, ensure_ascii=False)

        logger.info(f"结果已保存到: {output_json}")



def main():

    args = parse_args()


    # === ИНИЦИАЛИЗАЦИЯ И УСТАНОВКА ПОЛЬЗОВАТЕЛЬСКОЙ ДАТЫ СБОРКИ ===

    # Если аргумент передан, мы экспортируем KBUILD_BUILD_TIMESTAMP, 

    # чтобы системы сборки ядра (make / bazel) подхватили нужное время.

    if args.build_time:

        if args.build_time.strip().upper() == 'N':

            # Если передано 'N', генерируем текущую дату в формате UTC

            build_timestamp = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S UTC %Y")

        else:

            # Иначе используем строку, переданную пользователем

            build_timestamp = args.build_time.strip()

        

        os.environ["KBUILD_BUILD_TIMESTAMP"] = build_timestamp

        logger.info(f"应用自定义构建时间 (KBUILD_BUILD_TIMESTAMP): {build_timestamp}")

    # =============================================================


    if args.verbose:

        logging.getLogger().setLevel(logging.DEBUG)


    if args.list_configs:

        list_configs()

        return 0


    if args.list_matrix:

        list_matrix()

        return 0


    if not args.all and not args.matrix and not args.android:

        logger.error("请指定 --all, --matrix 或 --android")

        return 1


    workspace = args.workspace

    logger.info(f"工作目录: {workspace}")

    os.makedirs(workspace, exist_ok=True)


    results = []


    if args.all:

        results = build_all(args, workspace)

    elif args.matrix:

        results = build_matrix(args.matrix, args, workspace)

    else:

        try:

            config = create_build_config(args)

            result = build_single(config, workspace, args.dry_run)

            results.append(result)

        except Exception as e:

            logger.error(f"配置错误: {e}")

            return 1


    if results:

        print_summary(results, args.output_json)


    if results and all(r.success for r in results):

        return 0

    elif results and any(r.success for r in results):

        return 2

    return 1



if __name__ == "__main__":

    sys.exit(main()) 
