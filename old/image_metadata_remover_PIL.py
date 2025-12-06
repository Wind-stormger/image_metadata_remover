#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片元数据移除工具

该工具用于扫描指定路径中的所有图片和压缩包里的图片，移除图片中的所有元数据。
支持的图片格式：JPEG, PNG, WebP
注意：动态WebP图片会被跳过，以防止破坏文件。
"""

import os
import sys
import time
import threading
import zipfile
import subprocess
import shutil
import tempfile
import concurrent.futures
from PIL import Image
from PIL import ImageFile

# 确保Pillow支持大文件
ImageFile.LOAD_TRUNCATED_IMAGES = True

# 支持的图片格式
SUPPORTED_IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".webp"}

# 支持的压缩文件格式
SUPPORTED_ARCHIVE_FORMATS = {".zip"}

# 常量定义
MAX_RETRIES = 3  # 最大重试次数
MAX_ARCHIVE_WORKERS = 2  # 最大压缩文件并发数

def is_dynamic_webp(file_path):
    """
    检查WebP文件是否为动态WebP
    
    Args:
        file_path (str): WebP文件路径
        
    Returns:
        bool: True表示是动态WebP，False表示是静态WebP
    """
    try:
        with Image.open(file_path) as img:
            # 检查是否有多个帧
            return getattr(img, "is_animated", False)
    except Exception as e:
        print(f"检查WebP文件失败 {file_path}: {e}")
        return False

def has_metadata(file_path):
    """
    检查图片文件是否含有元数据
    
    Args:
        file_path (str): 图片文件路径
        
    Returns:
        bool: True表示含有元数据，False表示不含有元数据
    """
    try:
        with Image.open(file_path) as img:
            # 使用集合提高查找效率
            true_metadata_keys = {
                'exif', 'xmp', 'iptc', 'adobe',
                'title', 'author', 'description', 'copyright', 
                'creation_time', 'software', 'artist', 'make', 'model',
                'GPSInfo', 'location', 'latitude', 'longitude'
            }
            
            # 检查是否有真正的元数据键存在
            for key in img.info:
                if key in true_metadata_keys:
                    print(f"检测到元数据键: {key} 在文件 {file_path} 中")
                    return True
            
            # 针对不同格式的特殊处理
            if img.format == 'PNG':
                # PNG格式：检查是否有非必要的元数据
                necessary_keys = {'palette', 'transparency', 'gamma', 'icc_profile', 'dpi'}
                for key, value in img.info.items():
                    if key not in necessary_keys and isinstance(value, str) and len(value) > 0:
                        print(f"PNG检测到非必要元数据键: {key} 在文件 {file_path} 中")
                        return True
            
            # 针对WebP格式的特殊处理
            elif img.format == 'WEBP':
                # WebP格式：检查是否有非必要键
                necessary_keys = {'background', 'loop', 'gamma'}
                for key in img.info:
                    if key not in necessary_keys:
                        print(f"WEBP检测到非必要元数据键: {key} 在文件 {file_path} 中")
                        return True
            
            # 针对JPEG格式的特殊处理
            elif img.format == 'JPEG':
                # JPEG格式：只保留必要的jfif相关键
                jpeg_necessary_keys = {'jfif', 'jfif_version', 'jfif_unit', 'jfif_density', 'icc_profile', 'dpi'}
                for key in img.info:
                    if key not in jpeg_necessary_keys:
                        print(f"JPEG检测到非必要元数据键: {key} 在文件 {file_path} 中")
                        # 检查是否有其他可能的元数据
                        return True
            
            # 其他格式：如果info中还有其他键，可能包含元数据
            elif len(img.info) > 0:
                return True
            
            # 默认情况：没有元数据
            return False
    except Exception as e:
        print(f"检查元数据失败 {file_path}: {e}")
        # 发生错误时，默认不处理该文件，避免连锁错误
        return False

def remove_metadata_from_image(file_path):
    """
    移除图片中的所有元数据
    
    Args:
        file_path (str): 图片文件路径
        
    Returns:
        tuple: (success, skipped)
            success: True表示成功，False表示失败
            skipped: True表示跳过，False表示未跳过
    """
    
    # 检查文件扩展名
    ext = os.path.splitext(file_path)[1].lower()
    
    # 跳过不支持的格式
    if ext not in SUPPORTED_IMAGE_FORMATS:
        return False, False
    
    # 检查WebP是否为动态
    if ext == ".webp" and is_dynamic_webp(file_path):
        print(f"跳过动态WebP文件: {file_path}")
        return False, True
    
    # 检查是否含有元数据，没有则跳过处理
    if not has_metadata(file_path):
        # print(f"跳过无元数据文件: {file_path}")
        return False, True
    
    # 添加错误重试机制，最多重试MAX_RETRIES次
    for retry in range(MAX_RETRIES):
        try:
            # 打开图片并移除元数据
            with Image.open(file_path) as img:
                # 保存ICC配置文件（如果存在）
                icc_profile = img.info.get('icc_profile')
                
                # 创建一个新的图片对象，仅复制像素数据，不复制任何元数据
                # 这是清除所有元数据的最可靠方法，包括Adobe特定字段
                # 注意：保留原始图像模式，避免不必要的颜色空间转换
                # 不必要的颜色空间转换（如CMYK→RGB）会导致文件大小增加
                new_img = Image.new(img.mode, img.size)
                new_img.paste(img)
                
                # 获取原始文件大小和图像模式，用于调试
                original_size = os.path.getsize(file_path)
                original_mode = img.mode
                print(f"处理前 - 文件: {os.path.basename(file_path)}, 大小: {original_size/1024:.2f} KB, 模式: {original_mode}")
                
                # 使用临时文件保存处理后的图片，然后替换原文件
                # 这是最可靠的方法，确保原文件被完全覆盖
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as temp_file:
                    temp_file_path = temp_file.name
                
                try:
                    # 根据不同格式使用优化的保存参数
                    if ext in [".jpg", ".jpeg"]:
                        # JPEG：设置适中质量(80) + 优化，平衡质量和文件大小
                        # 关键：使用适中的质量值(80)，避免过高的质量导致文件增大
                        # 结合optimize=True，确保在保证质量的同时获得最佳压缩效果
                        new_img.save(temp_file_path, "JPEG", quality=80, optimize=True, exif=b"", xmp=b"", icc_profile=icc_profile)
                    elif ext == ".png":
                        # PNG：优化 + 最高压缩级别
                        # 压缩级别9是最高压缩，不会增加文件大小
                        new_img.save(temp_file_path, "PNG", optimize=True, compress_level=9, exif=b"", icc_profile=icc_profile)
                    elif ext == ".webp":
                        # WebP：无损压缩 + 优化
                        new_img.save(temp_file_path, "WEBP", lossless=True, optimize=True, exif=b"", icc_profile=icc_profile)
                    
                    # 关闭文件句柄，确保文件完全写入
                    new_img.close()
                    
                    # 获取处理后的文件大小
                    processed_size = os.path.getsize(temp_file_path)
                    
                    # 处理原文件替换 - 支持跨磁盘操作
                    try:
                        # 尝试使用os.replace() - 更高效，适合同一磁盘
                        os.replace(temp_file_path, file_path)
                    except OSError as e:
                        # 如果是跨磁盘操作，使用shutil.copy2() + os.remove()
                        if e.winerror == 17:  # 系统无法将文件移到不同的磁盘驱动器
                            import shutil
                            # 先复制文件，然后删除原文件，最后删除临时文件
                            shutil.copy2(temp_file_path, file_path)
                            os.remove(temp_file_path)
                        else:
                            # 其他错误重新抛出
                            raise
                    
                    print(f"处理后 - 文件: {os.path.basename(file_path)}, 大小: {processed_size/1024:.2f} KB, 变化: {(processed_size-original_size)/1024:.2f} KB")
                    print(f"已移除元数据: {file_path}")
                    return True, False
                finally:
                    # 清理临时文件（如果替换失败）
                    if os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except Exception as e:
                            print(f"清理临时文件失败 {temp_file_path}: {e}")
        except Exception as e:
            if retry < MAX_RETRIES - 1:
                print(f"处理图片失败 {file_path}，第 {retry + 1} 次重试: {e}")
                time.sleep(1)  # 等待1秒后重试
            else:
                print(f"处理图片失败 {file_path}，已重试 {MAX_RETRIES} 次: {e}")
                return False, False

def find_bandizip():
    """
    查找Bandizip可执行文件的路径
    
    Returns:
        str or None: Bandizip可执行文件的路径，如果找不到则返回None
    """
    # 常见的Bandizip安装路径
    possible_paths = [
        'bz',  # 在PATH中的情况
        r'C:\Program Files\Bandizip\bz.exe',
        r'C:\Program Files (x86)\Bandizip\bz.exe',
        r'D:\Program Files\Bandizip\bz.exe',
        r'D:\Program Files (x86)\Bandizip\bz.exe',
    ]
    
    for path in possible_paths:
        if os.path.exists(path) or (path == 'bz' and shutil.which('bz')):
            return path
    
    return None

def compress_with_bandizip(source, output_zip):
    bandizip_path = find_bandizip()
    if not bandizip_path:
        print(f"未找到Bandizip可执行文件")
        return False

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_zip), exist_ok=True)

    # 构建命令：使用相对路径，先进入源目录，然后压缩所有内容
    # 这样压缩包中就不会包含源目录本身
    cmd = [
        bandizip_path,
        "c",
        "-y",
        "-fmt:zip",
        "-l:9",
        "-r",
        output_zip,
        "."
    ]

    print(f"执行Bandizip命令: cd {source} && {' '.join(cmd)}")
    try:
        # 使用capture_output=True但不使用text=True，避免编码问题
        result = subprocess.run(cmd, cwd=source, check=True, capture_output=True)
        print(f"Bandizip命令执行成功")
        # 仅在调试时打印输出，避免编码问题
        # print(f"标准输出: {result.stdout.decode('utf-8', errors='replace')}")
        # if result.stderr:
        #     print(f"标准错误: {result.stderr.decode('utf-8', errors='replace')}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Bandizip压缩失败，返回码: {e.returncode}")
        # 安全地解码输出，避免编码问题
        stdout = e.stdout.decode('utf-8', errors='replace') if e.stdout else ""
        stderr = e.stderr.decode('utf-8', errors='replace') if e.stderr else ""
        if stdout:
            print(f"标准输出: {stdout}")
        if stderr:
            print(f"标准错误: {stderr}")
        return False
    except Exception as e:
        print(f"Bandizip调用异常: {type(e).__name__}: {e}")
        return False


def find_7zip():
    """
    查找7-Zip可执行文件的路径
    
    Returns:
        str or None: 7-Zip可执行文件的路径，如果找不到则返回None
    """
    # 常见的7-Zip安装路径
    possible_paths = [
        '7z',  # 在PATH中的情况
        r'C:\Program Files\7-Zip\7z.exe',
        r'C:\Program Files (x86)\7-Zip\7z.exe',
        r'D:\Program Files\7-Zip\7z.exe',
        r'D:\Program Files (x86)\7-Zip\7z.exe',
        r'/usr/bin/7z',  # Linux/Mac路径
        r'/usr/local/bin/7z',
    ]
    
    for path in possible_paths:
        if os.path.exists(path) or (path == '7z' and shutil.which('7z')):
            return path
    
    return None

def compress_with_7z_zip(source, output_zip):
    """
    使用7-Zip将文件/目录压缩为.zip（最高压缩）
    
    Args:
        source (str): 源文件或目录路径
        output_zip (str): 输出ZIP文件路径
        
    Returns:
        bool: 成功返回True，失败返回False
    """
    # 查找7-Zip
    seven_zip_path = find_7zip()
    if not seven_zip_path:
        print(f"未找到7-Zip可执行文件")
        return False
    
    try:
        cmd = [
            seven_zip_path, 'a',               # a = add to archive
            '-tzip',                 # 指定格式为 zip
            '-mx=9',                 # 最高压缩级别
            '-mmt=on',               # 启用多线程
            output_zip,
            "."                     # 使用当前目录（通过cwd参数进入源目录）
        ]
        
        print(f"执行7-Zip命令: cd {source} && {' '.join(cmd)}")
        # 使用capture_output=True但不使用text=True，避免编码问题
        result = subprocess.run(cmd, cwd=source, check=True, capture_output=True)
        print(f"7-Zip命令执行成功")
        # 安全地解码输出，避免编码问题
        stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ""
        stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ""
        if stdout:
            print(f"标准输出: {stdout}")
        if stderr:
            print(f"标准错误: {stderr}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"7-Zip压缩失败，返回码: {e.returncode}")
        print(f"执行命令: cd {source} && {' '.join(cmd)}")
        # 安全地解码输出，避免编码问题
        stdout = e.stdout.decode('utf-8', errors='replace') if e.stdout else ""
        stderr = e.stderr.decode('utf-8', errors='replace') if e.stderr else ""
        if stdout:
            print(f"标准输出: {stdout}")
        if stderr:
            print(f"标准错误: {stderr}")
        return False
    except Exception as e:
        print(f"7-Zip压缩失败: {type(e).__name__}: {e}")
        print(f"执行命令: cd {source} && {' '.join(cmd)}")
        return False


def process_archive_file(archive_path):
    """ 处理压缩文件，移除其中图片的元数据 """
    processed_count = 0
    temp_archive_path = None
    
    try:
        ext = os.path.splitext(archive_path)[1].lower()
        if ext != ".zip":
            print(f"跳过压缩文件 {archive_path}: 仅支持ZIP格式")
            return 0

        # 使用tempfile创建安全的临时目录，自动清理
        with tempfile.TemporaryDirectory() as temp_dir:
            # 解压原 ZIP
            with zipfile.ZipFile(archive_path, "r") as zf_read:
                zf_read.extractall(temp_dir)

            # 收集所有需要处理的图片文件
            image_files = []
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_ext = os.path.splitext(file)[1].lower()
                    if file_ext in SUPPORTED_IMAGE_FORMATS:
                        image_files.append(file_path)
            
            # 并行处理图片文件
            if image_files:
                print(f"压缩文件内并行处理 {len(image_files)} 个图片文件")
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # 提交所有图片文件处理任务
                    future_to_file = {executor.submit(remove_metadata_from_image, file_path): file_path for file_path in image_files}
                    
                    # 收集处理结果
                    for future in concurrent.futures.as_completed(future_to_file):
                        success, skipped = future.result()
                        if success:
                            processed_count += 1

            # 只有当处理了图片时才执行压缩
            if processed_count > 0:
                # 创建临时ZIP文件路径
                archive_dir = os.path.dirname(archive_path) or os.getcwd()
                temp_archive_path = tempfile.mktemp(suffix='.zip', dir=archive_dir)
                
                # 检查压缩工具是否可用
                bandizip_available = find_bandizip() is not None
                sevenzip_available = find_7zip() is not None
                
                # 尝试压缩
                compressed_success = False
                if bandizip_available:
                    compressed_success = compress_with_bandizip(temp_dir, temp_archive_path)
                elif sevenzip_available:
                    compressed_success = compress_with_7z_zip(temp_dir, temp_archive_path)
                else:
                    # 使用zipfile库压缩
                    print(f"使用Python内置zipfile库压缩")
                    try:
                        with zipfile.ZipFile(temp_archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf_write:
                            for root, dirs, files in os.walk(temp_dir):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    rel_path = os.path.relpath(file_path, temp_dir)
                                    zf_write.write(file_path, rel_path)
                        compressed_success = True
                    except Exception as e:
                        print(f"zipfile压缩失败: {e}")

                if compressed_success:
                    # 替换原文件
                    os.replace(temp_archive_path, archive_path)
                    print(f"已处理压缩文件: {archive_path}, 处理了 {processed_count} 张图片")
                else:
                    print(f"压缩失败，未替换原文件: {archive_path}")
            else:
                # 没有处理任何图片，直接保留旧zip压缩包
                print(f"压缩包内图片无元数据，无需处理: {archive_path}")

    except Exception as e:
        print(f"处理压缩文件失败 {archive_path}: {e}")
    finally:
        # 清理临时ZIP文件（如果存在）
        if temp_archive_path and os.path.exists(temp_archive_path):
            try:
                os.unlink(temp_archive_path)
            except Exception as e:
                print(f"清理临时文件失败 {temp_archive_path}: {e}")

    return processed_count


def _process_single_file(file_path):
    """
    处理单个文件，返回处理结果
    
    Args:
        file_path (str): 文件路径
        
    Returns:
        dict: 处理结果
    """
    result = {
        "total_processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "processed_in_archive": 0
    }
    
    ext = os.path.splitext(file_path)[1].lower()
    
    # 处理图片文件
    if ext in SUPPORTED_IMAGE_FORMATS:
        result["total_processed"] += 1
        success, skipped = remove_metadata_from_image(file_path)
        if skipped:
            result["skipped"] += 1
        elif success:
            result["success"] += 1
        else:
            result["failed"] += 1
    
    # 处理压缩文件
    elif ext in SUPPORTED_ARCHIVE_FORMATS:
        processed_in_archive = process_archive_file(file_path)
        result["processed_in_archive"] += processed_in_archive
        result["total_processed"] += processed_in_archive
        result["success"] += processed_in_archive
    
    else:
        print(f"跳过文件 {file_path}: 不支持的文件格式")
    
    return result


def scan_and_remove_metadata(root_path, recursive=True, max_workers=None):
    """
    扫描指定路径，移除所有图片和压缩包里图片的元数据
    支持处理单一图片文件、单一ZIP文件或目录
    
    Args:
        root_path (str): 根目录路径、单一图片文件路径或单一ZIP文件路径
        recursive (bool): 是否递归扫描子目录
        max_workers (int): 最大工作线程数，默认使用CPU核心数
        
    Returns:
        dict: 处理结果，包含成功、失败、跳过的数量和处理时间
    """
    
    # 记录开始时间
    start_time = time.time()
    
    result = {
        "total_processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "archives_processed": 0,
        "processing_time": 0
    }
    
    # 检查路径是否存在
    if not os.path.exists(root_path):
        print(f"路径不存在: {root_path}")
        return result
    
    # 直接分类收集文件，减少一次遍历
    image_files = []
    archive_files = []
    
    # 处理单一文件
    if os.path.isfile(root_path):
        ext = os.path.splitext(root_path)[1].lower()
        if ext in SUPPORTED_IMAGE_FORMATS:
            image_files.append(root_path)
        elif ext in SUPPORTED_ARCHIVE_FORMATS:
            archive_files.append(root_path)
    
    # 处理目录
    else:
        # 使用os.scandir替代os.walk，提高遍历效率
        def collect_files(current_dir):
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        # 直接分类收集文件
                        file_path = entry.path
                        ext = os.path.splitext(file_path)[1].lower()
                        if ext in SUPPORTED_IMAGE_FORMATS:
                            image_files.append(file_path)
                        elif ext in SUPPORTED_ARCHIVE_FORMATS:
                            archive_files.append(file_path)
                    elif entry.is_dir(follow_symlinks=False) and recursive:
                        # 递归处理子目录
                        collect_files(entry.path)
        
        # 开始收集文件
        collect_files(root_path)
    
    # 总文件数
    total_files = len(image_files) + len(archive_files)
    processed_files = 0
    progress_lock = threading.Lock()
    
    # 显示进度的辅助函数
    def update_progress():
        with progress_lock:
            nonlocal processed_files
            processed_files += 1
            if total_files > 0:
                progress = (processed_files / total_files) * 100
                elapsed_time = time.time() - start_time
                print(f"进度: {processed_files}/{total_files} ({progress:.1f}%) - 已用时: {elapsed_time:.2f}秒", end="\r")
    
    # 使用线程池并行处理文件
    if total_files > 0:
        print(f"开始处理 {total_files} 个文件...")
        
        # 并行处理图片文件
        if image_files:
            print(f"并行处理 {len(image_files)} 个图片文件")
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有图片文件处理任务
                future_to_file = {executor.submit(_process_single_file, file_path): file_path for file_path in image_files}
                
                # 收集处理结果
                for future in concurrent.futures.as_completed(future_to_file):
                    file_result = future.result()
                    result["total_processed"] += file_result["total_processed"]
                    result["success"] += file_result["success"]
                    result["failed"] += file_result["failed"]
                    result["skipped"] += file_result["skipped"]
                    update_progress()
        
        # 并行处理压缩文件（使用单独的线程池，限制并发数）
        if archive_files:
            print(f"并行处理 {len(archive_files)} 个压缩文件")
            # 限制压缩文件的并发数，避免资源竞争
            max_archive_workers = min(len(archive_files), MAX_ARCHIVE_WORKERS)  # 最多同时处理MAX_ARCHIVE_WORKERS个压缩文件
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_archive_workers) as executor:
                # 提交所有压缩文件处理任务
                future_to_archive = {executor.submit(_process_single_file, file_path): file_path for file_path in archive_files}
                
                # 收集处理结果
                for future in concurrent.futures.as_completed(future_to_archive):
                    file_result = future.result()
                    result["total_processed"] += file_result["total_processed"]
                    result["success"] += file_result["success"]
                    result["failed"] += file_result["failed"]
                    result["skipped"] += file_result["skipped"]
                    result["archives_processed"] += 1
                    update_progress()
        
        # 打印换行，避免进度信息被覆盖
        print()
    
    # 记录结束时间并计算处理时间
    end_time = time.time()
    result["processing_time"] = end_time - start_time
    
    return result

def main():
    """
    主函数，用于命令行调用
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="图片元数据移除工具")
    parser.add_argument("path", help="要扫描的目录或文件路径")
    parser.add_argument("--non-recursive", action="store_false", dest="recursive", help="不递归扫描子目录")
    parser.add_argument("--max-workers", type=int, default=None, help="最大工作线程数，默认使用CPU核心数")
    
    args = parser.parse_args()
    
    # 检查路径是否存在
    if not os.path.exists(args.path):
        print(f"错误: 路径不存在 {args.path}")
        sys.exit(1)
    
    # 执行扫描和处理
    print(f"开始扫描路径: {args.path}")
    result = scan_and_remove_metadata(args.path, args.recursive, args.max_workers)
    
    # 打印结果
    print("\n处理结果:")
    print(f"总处理文件数: {result['total_processed']}")
    print(f"成功: {result['success']}")
    print(f"失败: {result['failed']}")
    print(f"跳过: {result['skipped']}")
    print(f"处理的压缩文件数: {result['archives_processed']}")
    print(f"处理时间: {result['processing_time']:.2f} 秒")

if __name__ == "__main__":
    main()
