#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片元数据移除工具 - Tkinter GUI版本

使用Tkinter框架创建的图形界面，用于调用现有的图片元数据移除功能
"""

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext
from typing import Optional, Dict, Any

# 添加当前目录到Python路径，确保能导入现有模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from image_metadata_remover import scan_and_remove_metadata

class ImageMetadataRemoverTkinterGUI:
    """图片元数据移除工具Tkinter GUI类"""
    
    def __init__(self):
        """初始化GUI应用"""
        self.root = tk.Tk()
        self.root.title("图片元数据移除工具")
        self.root.geometry("600x600")
        self.root.resizable(True, True)
        
        # 变量初始化
        self.selected_path: Optional[str] = None
        self.is_recursive: bool = True
        self.max_workers: Optional[int] = None
        self.is_processing: bool = False
        self.processing_thread: Optional[threading.Thread] = None
        self.process_result: Dict[str, Any] = {}
        self.start_time: float = 0.0
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """初始化UI界面"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = ttk.Label(main_frame, text="图片元数据移除工具", font=('Arial', 16, 'bold'))
        title_label.pack(pady=10)
        
        # 路径选择部分
        path_frame = ttk.LabelFrame(main_frame, text="路径选择", padding="10")
        path_frame.pack(fill=tk.X, pady=5)
        
        self.path_var = tk.StringVar()
        path_entry = ttk.Entry(path_frame, textvariable=self.path_var, width=50)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        browse_btn = ttk.Button(path_frame, text="浏览", command=self.browse_path)
        browse_btn.pack(side=tk.LEFT)
        
        # 参数设置部分
        params_frame = ttk.LabelFrame(main_frame, text="参数设置", padding="10")
        params_frame.pack(fill=tk.X, pady=5)
        
        # 递归选项
        recursive_var = tk.BooleanVar(value=self.is_recursive)
        recursive_check = ttk.Checkbutton(params_frame, text="递归处理子文件夹", 
                                         variable=recursive_var, 
                                         command=lambda: setattr(self, 'is_recursive', recursive_var.get()))
        recursive_check.pack(anchor=tk.W, pady=2)
        
        # 最大工作线程数
        workers_frame = ttk.Frame(params_frame)
        workers_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(workers_frame, text="最大工作线程数:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.workers_var = tk.StringVar()
        workers_entry = ttk.Entry(workers_frame, textvariable=self.workers_var, width=10)
        workers_entry.pack(side=tk.LEFT)
        
        ttk.Label(workers_frame, text="(默认使用CPU核心数)").pack(side=tk.LEFT, padx=(5, 0))
        
        # 添加样式
        style = ttk.Style()
        
        # 优化按钮样式 - 使用ttk内置的按钮样式，确保跨平台一致性
        # 对于开始按钮，使用绿色背景和白色文字
        style.configure("Start.TButton", font=('Arial', 10, 'bold'), padding=6)
        # 使用map确保不同状态下的样式一致性
        style.map("Start.TButton", 
                 foreground=[('pressed', 'white'), ('disabled', 'gray')],
                 background=[('pressed', '!disabled', '#006400'), ('active', '#008000')])
        
        # 对于停止按钮，使用红色背景和白色文字
        style.configure("Stop.TButton", font=('Arial', 10, 'bold'), padding=6)
        style.map("Stop.TButton",
                 foreground=[('pressed', 'white'), ('disabled', 'gray')],
                 background=[('pressed', '!disabled', '#8B0000'), ('active', '#FF0000')])
        
        # 控制按钮部分
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        
        self.start_btn = ttk.Button(btn_frame, text="开始处理", command=self.start_processing, style="Start.TButton")
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.stop_btn = ttk.Button(btn_frame, text="停止处理", command=self.stop_processing, state=tk.DISABLED, style="Stop.TButton")
        self.stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 状态和进度部分
        status_frame = ttk.LabelFrame(main_frame, text="处理状态", padding="10")
        status_frame.pack(fill=tk.X, pady=5)
        
        self.status_var = tk.StringVar(value="就绪")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, font=('Arial', 10))
        status_label.pack(anchor=tk.W, pady=2)
        
        self.progress_bar = ttk.Progressbar(status_frame, mode='indeterminate')
        self.progress_bar.pack(fill=tk.X, pady=5)
        
        # 结果显示部分
        result_frame = ttk.LabelFrame(main_frame, text="处理结果", padding="10")
        result_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 创建结果文本区域
        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD, height=15)
        self.result_text.pack(fill=tk.BOTH, expand=True)
    
    def browse_path(self):
        """浏览并选择文件或文件夹"""
        path = filedialog.askdirectory()
        if path:
            self.path_var.set(path)
            self.selected_path = path
    
    def start_processing(self):
        """开始处理"""
        # 验证输入
        path = self.path_var.get().strip()
        if not path:
            self.show_message("请选择文件或文件夹", "警告")
            return
        
        if not os.path.exists(path):
            self.show_message("选择的路径不存在", "错误")
            return
        
        # 检查是否正在处理
        if self.is_processing:
            self.show_message("正在处理中，请稍候", "警告")
            return
        
        # 获取最大工作线程数
        max_workers = None
        workers_text = self.workers_var.get().strip()
        if workers_text:
            try:
                max_workers = int(workers_text)
                if max_workers <= 0:
                    raise ValueError("工作线程数必须大于0")
            except ValueError as e:
                self.show_message(f"无效的工作线程数: {e}", "错误")
                return
        
        # 更新UI状态
        self.is_processing = True
        self.selected_path = path
        self.max_workers = max_workers
        self.start_time = time.time()
        
        # 更新UI
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("处理中...")
        self.progress_bar.start()
        self.result_text.delete(1.0, tk.END)
        
        # 创建并启动处理线程
        self.processing_thread = threading.Thread(
            target=self._process_metadata,
            daemon=True
        )
        self.processing_thread.start()
        
        # 开始状态更新
        self.root.after(100, self.update_status)
    
    def stop_processing(self):
        """停止处理"""
        if self.is_processing and self.processing_thread:
            self.is_processing = False
            self.status_var.set("停止处理中...")
    
    def _process_metadata(self):
        """处理图片元数据的实际逻辑"""
        try:
            # 调用现有的处理函数
            self.process_result = scan_and_remove_metadata(
                root_path=self.selected_path,
                recursive=self.is_recursive,
                max_workers=self.max_workers
            )
        except Exception as e:
            # 处理错误，更新结果
            self.process_result = {
                'total_processed': 0,
                'success': 0,
                'failed': 0,
                'skipped': 0,
                'archives_processed': 0,
                'processing_time': time.time() - self.start_time,
                'original_size_total': 0,
                'processed_size_total': 0,
                'size_reduction_total': 0
            }
            self.append_result(f"处理过程中发生错误: {e}")
        finally:
            self.is_processing = False
            self.root.after(0, self._update_result_display)
    
    def update_status(self):
        """更新状态显示"""
        if self.is_processing:
            elapsed = time.time() - self.start_time
            self.status_var.set(f"处理中... 已用时 {elapsed:.2f}秒")
            self.root.after(1000, self.update_status)
    
    def _update_result_display(self):
        """更新结果显示"""
        # 更新UI状态
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("处理完成")
        self.progress_bar.stop()
        
        # 显示处理结果
        self.append_result("\n处理结果:")
        self.append_result(f"总处理文件数: {self.process_result.get('total_processed', 0)}")
        self.append_result(f"成功: {self.process_result.get('success', 0)}")
        self.append_result(f"失败: {self.process_result.get('failed', 0)}")
        self.append_result(f"跳过: {self.process_result.get('skipped', 0)}")
        self.append_result(f"处理的压缩文件数: {self.process_result.get('archives_processed', 0)}")
        
        # 体积统计输出
        original_size = self.process_result.get('original_size_total', 0)
        processed_size = self.process_result.get('processed_size_total', 0)
        size_reduction = self.process_result.get('size_reduction_total', 0)
        
        if original_size > 0 or self.process_result.get('archives_processed', 0) > 0:
            original_kb = original_size / 1024
            processed_kb = processed_size / 1024
            reduction_kb = size_reduction / 1024
            reduction_percent = 0
            if original_size > 0:
                reduction_percent = (size_reduction / original_size) * 100
            
            self.append_result("\n体积统计:")
            self.append_result(f"总原始体积: {original_kb:.2f} KB")
            self.append_result(f"总处理后体积: {processed_kb:.2f} KB")
            self.append_result(f"总体积减少: {reduction_kb:.2f} KB ({reduction_percent:.2f}%)")
        
        processing_time = self.process_result.get('processing_time', 0.0)
        self.append_result(f"\n处理时间: {processing_time:.2f} 秒")
    
    def append_result(self, text):
        """向结果文本框添加内容"""
        def _append():
            self.result_text.insert(tk.END, text + "\n")
            self.result_text.see(tk.END)
        
        # 确保在主线程中更新UI
        self.root.after(0, _append)
    
    def show_message(self, message, title="提示"):
        """显示消息对话框"""
        tk.messagebox.showinfo(title, message)
    
    def run(self):
        """运行GUI应用"""
        self.root.mainloop()


def main():
    """主函数"""
    gui = ImageMetadataRemoverTkinterGUI()
    gui.run()


if __name__ == '__main__':
    main()
