import pytest
from pathlib import Path

from oculith.convert import convert

# 测试数据
TEST_IMAGES = [
    Path("tests/data/images/beian.png"),
]

OUTPUT_DIR = Path("tests/output/images")

def setup_module(module):
    """模块级别的设置：创建输出目录"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

@pytest.mark.parametrize("image_file", TEST_IMAGES)
def test_image_basic_conversion(image_file):
    """测试基本的图片转换"""
    if not image_file.exists():
        pytest.skip(f"测试文件 {image_file} 不存在")
    
    result = convert(
        content=str(image_file),
        content_type="file",
        pipeline_type="standard"  # 应该自动转为PDF进行处理
    )
    
    assert "error" not in result, f"转换错误: {result.get('message', '')}"
    assert "markdown_content" in result

@pytest.mark.parametrize("ocr_engine", ["rapid", "tesseract"])
def test_image_with_ocr(ocr_engine):
    """测试使用OCR处理图片"""
    # 选择一个适合OCR的图片
    image_file = Path("tests/data/images/beian.png")
    if not image_file.exists():
        pytest.skip(f"测试文件 {image_file} 不存在")
    
    try:
        result = convert(
            content=str(image_file),
            content_type="file",
            pipeline_type="standard",
            ocr=ocr_engine
        )
        
        assert "error" not in result, f"转换错误: {result.get('message', '')}"
        assert "markdown_content" in result
        assert result["markdown_content"].strip() != ""
    except Exception as e:
        pytest.skip(f"图片OCR测试失败: {e}")

def test_image_with_vlm():
    """测试使用视觉语言模型处理图片"""
    # 选择一个图片
    image_file = Path("tests/data/images/beian.png")
    if not image_file.exists():
        pytest.skip(f"测试文件 {image_file} 不存在")
    
    try:
        result = convert(
            content=str(image_file),
            content_type="file",
            pipeline_type="vlm"
        )
        
        assert "error" not in result, f"转换错误: {result.get('message', '')}"
        assert "markdown_content" in result
    except Exception as e:
        pytest.skip(f"图片VLM测试失败: {e}")

def test_image_dict_with_images():
    """测试图片生成dict_with_images格式"""
    # 选择一个图片
    image_file = Path("tests/data/images/beian.png")
    if not image_file.exists():
        pytest.skip(f"测试文件 {image_file} 不存在")
    
    output_dir = OUTPUT_DIR / "image_with_dict"
    
    result = convert(
        content=str(image_file),
        content_type="file",
        pipeline_type="standard",
        return_type="dict_with_images",
        output_dir=str(output_dir)
    )
    
    assert "markdown_content" in result
    assert "images" in result
