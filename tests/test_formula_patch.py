#!/usr/bin/env python3
"""使用Monkey Patch解决tokenizer问题"""

import os
import sys

def patch_tokenizer():
    """补丁AutoTokenizer的from_pretrained方法"""
    from transformers import AutoTokenizer
    
    # 保存原始方法
    original_from_pretrained = AutoTokenizer.from_pretrained
    
    @classmethod
    def patched_from_pretrained(cls, pretrained_model_name_or_path, *args, **kwargs):
        """强制使用慢速tokenizer的补丁方法"""
        # 强制设置use_fast=False
        kwargs['use_fast'] = False
        print(f"🔧 补丁生效: 强制对 {pretrained_model_name_or_path} 使用慢速tokenizer")
        return original_from_pretrained(pretrained_model_name_or_path, *args, **kwargs)
    
    # 替换方法
    AutoTokenizer.from_pretrained = patched_from_pretrained
    print("✅ Monkey patch已应用")

def test_with_monkey_patch():
    """使用monkey patch测试"""
    print("🔧 应用monkey patch...")
    patch_tokenizer()
    
    # 现在导入和测试
    from oculith.convert import convert
    from pathlib import Path
    
    pdf_file = Path("tests/data/pdf/picture_classification.pdf")
    if not pdf_file.exists():
        print("❌ 测试文件不存在")
        return False
    
    print("🔄 测试公式理解功能...")
    
    try:
        result = convert(
            content=str(pdf_file),
            content_type="file",
            pipeline="standard",
            ocr="rapid",
            enable_formula_enrichment=True
        )
        
        if "error" in result:
            print(f"❌ 转换失败: {result['message']}")
            return False
        else:
            print("✅ 公式理解功能测试成功!")
            return True
            
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_with_monkey_patch()
    if success:
        print("\n🎉 Monkey patch方案有效!")
    else:
        print("\n😞 Monkey patch方案也无效")