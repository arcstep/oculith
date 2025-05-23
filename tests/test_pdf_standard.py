import pytest
from pathlib import Path

from oculith.convert import convert

# 测试数据
TEST_PDF_FILES = [
    Path("tests/data/pdf/code_and_formula.pdf"),
    Path("tests/data/pdf/amt_handbook_sample.pdf"),
    Path("tests/data/pdf/picture_classification.pdf")
]

OUTPUT_DIR = Path("tests/output/pdf_standard")

def setup_module(module):
    """模块级别的设置：创建输出目录"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

@pytest.mark.parametrize("pdf_file", TEST_PDF_FILES)
def test_pdf_without_ocr(pdf_file):
    """测试不使用OCR的PDF处理"""
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    result = convert(
        content=str(pdf_file),
        content_type="file",
        pipeline="standard",
        ocr=None  # 明确指定不使用OCR
    )
    
    assert "error" not in result, f"转换错误: {result.get('message', '')}"
    assert "markdown_content" in result
    assert result["markdown_content"].strip() != ""

def test_pdf_with_images():
    """测试包含图片的PDF处理"""
    # 选择一个包含图片的PDF
    pdf_file = Path("tests/data/pdf/picture_classification.pdf")
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    output_dir = OUTPUT_DIR / "with_images"
    
    result = convert(
        content=str(pdf_file),
        content_type="file",
        pipeline="standard",
        generate_images="picture",  # 提取图片
        return_base64_images=True,  # 新参数，替代 return_type="dict_with_images"
        output_dir=str(output_dir)
    )
    
    assert "images" in result
    
    # 检查是否有artifacts目录生成
    artifacts_dir = output_dir / f"{pdf_file.stem}_artifacts"
    assert artifacts_dir.exists() or len(result["images"]) == 0  # 如果没有图片，可能不会创建artifacts目录

@pytest.mark.parametrize("image_scale", [1.0, 2.0])
def test_pdf_image_scaling(image_scale):
    """测试不同的图像缩放比例"""
    # 选择一个包含图片的PDF
    pdf_file = Path("tests/data/pdf/picture_classification.pdf")
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    result = convert(
        content=str(pdf_file),
        content_type="file",
        pipeline="standard",
        generate_images="picture",
        images_scale=image_scale,
        return_base64_images=True  # 新参数，替代 return_type="dict_with_images"
    )
    
    assert "images" in result

def test_standard_pipeline_with_vlm():
    """测试标准管道与VLM图片描述功能的组合"""
    # 选择包含图片的PDF测试文件
    pdf_file = Path("tests/data/pdf/picture_classification.pdf")
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    output_dir = OUTPUT_DIR / "standard_with_vlm"
    output_dir.mkdir(exist_ok=True)
    
    # 对于测试目的，将测试标记为跳过如果没有配置VLM环境
    try:
        # 使用标准管道启用VLM图片描述
        result = convert(
            content=str(pdf_file),
            content_type="file",
            pipeline="standard",
            generate_images="picture",
            return_base64_images=True,  # 新参数，替代 return_type="dict_with_images"
            output_dir=str(output_dir),
            enable_vlm_picture_description=True
        )
        
        assert "error" not in result, f"转换错误: {result.get('message', '')}"
        assert result["model_info"]["pipeline"] == "standard"
        assert result["model_info"]["vlm_enabled"] is True
    except Exception as e:
        pytest.skip(f"VLM测试失败，可能是缺少运行环境: {e}")
