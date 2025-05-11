import pytest
from pathlib import Path
import os

from oculith.convert import convert

# 测试数据
TEST_FILES = {
    "md": Path("tests/data/md/duck.md"),
    "docx": Path("tests/data/docx/lorem_ipsum.docx"),
    "html": Path("tests/data/html/example_03.html"),
}

OUTPUT_DIR = Path("tests/output/simple")

@pytest.mark.parametrize("format_type", TEST_FILES.keys())
def test_basic_conversion(format_type):
    """测试基本转换功能"""
    test_file = TEST_FILES[format_type]
    
    # 跳过不存在的测试文件
    if not test_file.exists():
        pytest.skip(f"测试文件 {test_file} 不存在")
    
    result = convert(
        content=str(test_file),
        content_type="file",
        file_type=format_type,
        pipeline_type="simple"
    )
    
    # 基本检查
    assert "error" not in result, f"转换错误: {result.get('message', '')}"
    assert "markdown_content" in result
    assert result["markdown_content"].strip() != ""

def test_different_content_types():
    """测试不同内容类型的输入"""
    # 文件路径
    result_file = convert(
        content=str(TEST_FILES["md"]),
        content_type="file"
    )
    assert "markdown_content" in result_file
    
    # URL内容
    url = "https://docling-project.github.io/docling/concepts/architecture/"
    try:
        result_url = convert(
            content=url,
            content_type="url"
        )
        assert "markdown_content" in result_url
    except Exception as e:
        pytest.skip(f"URL测试跳过: {e}")
    
    # Base64内容
    with open(TEST_FILES["md"], "rb") as f:
        import base64
        b64_content = base64.b64encode(f.read()).decode("utf-8")
    
        result_b64 = convert(
            content=b64_content,
            content_type="base64",
            file_type="md"
        )
        assert "markdown_content" in result_b64

def test_output_formats():
    """测试不同输出格式"""
    test_file = TEST_FILES["md"]
    
    # 测试Markdown输出
    result_md = convert(
        content=str(test_file),
        content_type="file",
        return_type="markdown"
    )
    assert "markdown_content" in result_md
    
    # 测试嵌入式Markdown输出
    result_embedded = convert(
        content=str(test_file),
        content_type="file",
        return_type="markdown_embedded"
    )
    assert "markdown_content" in result_embedded
    
    # 测试带图像的字典输出
    result_dict = convert(
        content=str(test_file),
        content_type="file",
        return_type="dict_with_images"
    )
    assert "markdown_content" in result_dict
    assert "images" in result_dict

def test_output_to_file():
    """测试输出到文件"""
    test_file = TEST_FILES["md"]
    # 修改为目录路径
    output_dir = OUTPUT_DIR / "output_test"
    
    result = convert(
        content=str(test_file),
        content_type="file",
        output_dir=str(output_dir)
    )
    
    # 寻找生成的MD文件
    md_files = list(Path(output_dir).glob("*.md"))
    assert len(md_files) > 0
    
    with open(md_files[0], "r", encoding="utf-8") as f:
        content = f.read()
        assert content.strip() != ""
