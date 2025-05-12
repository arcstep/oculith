import time
import os
from pathlib import Path

# 导入三个不同的PDF处理库
from PyPDF2 import PdfReader
from pdfminer.high_level import extract_text as pdfminer_extract
import pdfplumber

def extract_with_pypdf2(pdf_path):
    """使用PyPDF2提取PDF文本"""
    start_time = time.time()
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n\n"
    end_time = time.time()
    return text, end_time - start_time

def extract_with_pdfminer(pdf_path):
    """使用pdfminer.six提取PDF文本"""
    start_time = time.time()
    text = pdfminer_extract(pdf_path)
    end_time = time.time()
    return text, end_time - start_time

def extract_with_pdfplumber(pdf_path):
    """使用pdfplumber提取PDF文本"""
    start_time = time.time()
    with pdfplumber.open(pdf_path) as pdf:
        text = ""
        for page in pdf.pages:
            text += page.extract_text() + "\n\n"
    end_time = time.time()
    return text, end_time - start_time

def save_to_file(text, filename):
    """保存文本到文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(text)

def evaluate_results(file_path, output_dir):
    """评估三种方法的结果并输出到各自文件"""
    pdf_path = Path(file_path)
    if not pdf_path.exists():
        print(f"文件未找到: {pdf_path}")
        return
    
    # 创建输出目录
    out_dir = Path(output_dir)
    out_dir.mkdir(exist_ok=True, parents=True)
    
    print(f"正在处理PDF: {pdf_path}")
    
    # 使用三种库提取文本
    print("1. 使用PyPDF2提取文本...")
    pypdf2_text, pypdf2_time = extract_with_pypdf2(pdf_path)
    pypdf2_file = out_dir / f"{pdf_path.stem}_pypdf2.txt"
    save_to_file(pypdf2_text, pypdf2_file)
    
    print("2. 使用pdfminer.six提取文本...")
    pdfminer_text, pdfminer_time = extract_with_pdfminer(pdf_path)
    pdfminer_file = out_dir / f"{pdf_path.stem}_pdfminer.txt"
    save_to_file(pdfminer_text, pdfminer_file)
    
    print("3. 使用pdfplumber提取文本...")
    pdfplumber_text, pdfplumber_time = extract_with_pdfplumber(pdf_path)
    pdfplumber_file = out_dir / f"{pdf_path.stem}_pdfplumber.txt"
    save_to_file(pdfplumber_text, pdfplumber_file)
    
    # 输出性能评估结果
    print("\n性能评估结果:")
    print(f"{'库名':<15}{'用时(秒)':<10}{'文本长度':<15}")
    print(f"{'-'*40}")
    print(f"{'PyPDF2':<15}{pypdf2_time:.4f}s{len(pypdf2_text):<15}")
    print(f"{'pdfminer.six':<15}{pdfminer_time:.4f}s{len(pdfminer_text):<15}")
    print(f"{'pdfplumber':<15}{pdfplumber_time:.4f}s{len(pdfplumber_text):<15}")
    
    # 简单的输出差异评估
    print("\n输出结果评估:")
    print(f"PyPDF2文本输出到: {pypdf2_file}")
    print(f"pdfminer.six文本输出到: {pdfminer_file}")
    print(f"pdfplumber文本输出到: {pdfplumber_file}")
    
    # 保存性能评估结果
    eval_file = out_dir / f"{pdf_path.stem}_evaluation.txt"
    with open(eval_file, 'w', encoding='utf-8') as f:
        f.write("PDF文本提取性能评估\n")
        f.write(f"文件: {pdf_path}\n\n")
        f.write(f"{'库名':<15}{'用时(秒)':<10}{'文本长度':<15}\n")
        f.write(f"{'-'*40}\n")
        f.write(f"{'PyPDF2':<15}{pypdf2_time:.4f}s{len(pypdf2_text):<15}\n")
        f.write(f"{'pdfminer.six':<15}{pdfminer_time:.4f}s{len(pdfminer_text):<15}\n")
        f.write(f"{'pdfplumber':<15}{pdfplumber_time:.4f}s{len(pdfplumber_text):<15}\n")
    
    print(f"\n评估结果已保存到: {eval_file}")

if __name__ == "__main__":
    pdf_file = "./data/pdf/beian.pdf"
    output_dir = "./output/pdf_extract_results"
    evaluate_results(pdf_file, output_dir)
