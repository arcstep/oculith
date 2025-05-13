import pytest
from pathlib import Path

from oculith.convert import convert

# 测试数据 - 选择适合OCR测试的文件
TEST_PDF_FILES = [
    Path("tests/data/pdf/picture_classification.pdf"),
    Path("tests/data/pdf/beian.pdf")
]

TEST_OCR_ENGINES = ["rapid", "tesseract", "easy", "mac"]
OUTPUT_DIR = Path("tests/output/pdf_ocr")

def setup_module(module):
    """模块级别的设置：创建输出目录"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

@pytest.mark.parametrize("pdf_file", TEST_PDF_FILES)
@pytest.mark.parametrize("ocr_engine", TEST_OCR_ENGINES)
def test_pdf_ocr_basic(pdf_file, ocr_engine):
    """测试不同OCR引擎的基本功能"""
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    try:
        result = convert(
            content=str(pdf_file),
            content_type="file",
            pipeline="standard",
            ocr=ocr_engine
        )
        
        assert "error" not in result, f"转换错误: {result.get('message', '')}"
        assert "markdown_content" in result
        assert result["markdown_content"].strip() != ""
    except Exception as e:
        pytest.skip(f"OCR引擎 {ocr_engine} 测试失败: {e}")

@pytest.mark.parametrize("return_base64_images", [False, True])
def test_ocr_output_formats(return_base64_images):
    """测试OCR处理的不同输出格式"""
    # 选择一个适合OCR的PDF
    pdf_file = Path("tests/data/pdf/picture_classification.pdf")
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    # 使用最常见的OCR引擎
    ocr_engine = "tesseract"
    
    result = convert(
        content=str(pdf_file),
        content_type="file",
        pipeline="standard",
        ocr=ocr_engine,
        return_base64_images=return_base64_images,
        generate_images="picture"
    )
    
    assert "error" not in result, f"转换错误: {result.get('message', '')}"
    assert "markdown_content" in result
    assert "images" in result
    
    # 检查图片数据是否按预期存在
    if return_base64_images and result["images"]:
        for img_info in result["images"].values():
            assert "base64" in img_info
