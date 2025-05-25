#!/usr/bin/env python3
"""调试公式理解模型加载问题"""

import os
import sys
import traceback
from pathlib import Path

def check_transformers_version():
    """检查transformers版本"""
    try:
        import transformers
        print(f"✅ Transformers版本: {transformers.__version__}")
        return True
    except ImportError as e:
        print(f"❌ 无法导入transformers: {e}")
        return False

def check_tokenizers_version():
    """检查tokenizers版本"""
    try:
        import tokenizers
        print(f"✅ Tokenizers版本: {tokenizers.__version__}")
        return True
    except ImportError as e:
        print(f"❌ 无法导入tokenizers: {e}")
        return False

def test_huggingface_cache():
    """检查HuggingFace缓存状态"""
    cache_dir = Path.home() / ".cache" / "huggingface"
    if cache_dir.exists():
        print(f"✅ HuggingFace缓存目录存在: {cache_dir}")
        hub_dir = cache_dir / "hub"
        if hub_dir.exists():
            models = list(hub_dir.glob("models--*"))
            print(f"📦 缓存的模型数量: {len(models)}")
            for model in models[:5]:  # 只显示前5个
                print(f"   - {model.name}")
        return True
    else:
        print(f"❌ HuggingFace缓存目录不存在: {cache_dir}")
        return False

def test_correct_formula_model():
    """测试实际的公式理解模型"""
    print("🔬 测试实际的公式理解模型:")
    
    # 从缓存看到的实际模型名称
    model_name = "ds4sd/CodeFormula"
    print(f"🎯 测试模型: {model_name}")
    
    try:
        from transformers import AutoTokenizer
        
        print("🔄 尝试加载tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=True,
            cache_dir=None
        )
        print("✅ Tokenizer加载成功!")
        
        # 测试tokenizer基本功能
        test_text = "E = mc^2"
        tokens = tokenizer.encode(test_text)
        print(f"✅ Tokenizer功能测试成功: '{test_text}' -> {len(tokens)} tokens")
        
        return True
        
    except Exception as e:
        print(f"❌ 模型加载失败:")
        print(f"   错误类型: {type(e).__name__}")
        print(f"   错误信息: {str(e)}")
        
        if "ModelWrapper" in str(e):
            print("\n🎯 这就是原始的 ModelWrapper 错误!")
            print("   这确实是tokenizer.json文件的格式问题")
            
            # 检查缓存文件状态
            cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
            model_dir = cache_dir / "models--ds4sd--CodeFormula"
            if model_dir.exists():
                print(f"\n📁 模型缓存目录: {model_dir}")
                
                # 查找tokenizer文件
                tokenizer_files = list(model_dir.rglob("tokenizer.json"))
                if tokenizer_files:
                    tokenizer_file = tokenizer_files[0]
                    print(f"📄 找到tokenizer文件: {tokenizer_file}")
                    print(f"   文件大小: {tokenizer_file.stat().st_size} bytes")
                    
                    # 尝试读取文件开头，看是否是有效JSON
                    try:
                        with open(tokenizer_file, 'r') as f:
                            content = f.read(100)  # 读取前100个字符
                            print(f"   文件开头: {content[:50]}...")
                    except Exception as read_error:
                        print(f"   ❌ 无法读取文件: {read_error}")
                else:
                    print("❌ 未找到tokenizer.json文件")
        
        print("\n📋 完整错误堆栈:")
        traceback.print_exc()
        return False

def test_architecture():
    """检查系统架构信息"""
    import platform
    import subprocess
    
    print(f"\n🏗️ 系统架构信息:")
    print(f"   系统: {platform.system()}")
    print(f"   架构: {platform.machine()}")
    print(f"   Python架构: {platform.architecture()}")
    
    # 检查Python是否为原生编译
    try:
        result = subprocess.run(['file', sys.executable], 
                              capture_output=True, text=True)
        print(f"   Python可执行文件架构: {result.stdout.strip()}")
    except:
        pass

def main():
    """主函数"""
    print("🔍 公式理解模型加载问题诊断")
    print("=" * 50)
    
    # 基础检查
    if not check_transformers_version():
        return
    
    if not check_tokenizers_version():
        return
        
    # 缓存检查
    test_huggingface_cache()
    
    # 架构检查
    test_architecture()
    
    # 核心测试
    success = test_correct_formula_model()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ 诊断完成 - 模型加载正常")
    else:
        print("❌ 诊断完成 - 发现问题需要解决")
        print("\n🔧 解决方案:")
        print("1. 删除损坏的模型缓存:")
        print("   rm -rf ~/.cache/huggingface/hub/models--ds4sd--CodeFormula")
        print("2. 重新运行测试，让模型重新下载")

if __name__ == "__main__":
    main()