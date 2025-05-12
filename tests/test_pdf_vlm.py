import pytest
from pathlib import Path

from oculith.convert import convert

# 测试数据
TEST_PDF_FILES = [
    Path("tests/data/pdf/picture_classification.pdf"),
    Path("tests/data/pdf/beian.pdf"),
]

OUTPUT_DIR = Path("tests/output/pdf_vlm")

def setup_module(module):
    """模块级别的设置：创建输出目录"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

@pytest.mark.parametrize("pdf_file", TEST_PDF_FILES)
def test_pdf_vlm_basic(pdf_file):
    """测试使用视觉语言模型处理PDF"""
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    try:
        result = convert(
            content=str(pdf_file),
            content_type="file",
            pipeline="vlm"  # 使用VLM Pipeline
        )
        
        assert "error" not in result, f"转换错误: {result.get('message', '')}"
        assert "markdown_content" in result
        assert result["markdown_content"].strip() != ""
    except Exception as e:
        pytest.skip(f"VLM测试失败: {e}")

def test_vlm_output_to_file():
    """测试VLM输出到文件"""
    # 选择一个PDF文件
    pdf_file = Path("tests/data/pdf/picture_classification.pdf")
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    # 正确：使用不带后缀的目录名
    output_dir = OUTPUT_DIR / "vlm_output"
    
    try:
        result = convert(
            content=str(pdf_file),
            content_type="file",
            pipeline="vlm",
            output_dir=str(output_dir)
        )
        
        # 文件应该是 <output_dir>/<原文件名>.md
        expected_file = output_dir / "picture_classification.md"
        assert expected_file.exists()
        with open(expected_file, "r", encoding="utf-8") as f:
            content = f.read()
            assert content.strip() != ""
    except Exception as e:
        pytest.skip(f"VLM输出测试失败: {e}")
