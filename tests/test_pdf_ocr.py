import pytest
from pathlib import Path

from oculith.convert import convert, check_ocr_engine_availability

# 测试数据 - 选择适合OCR测试的文件
TEST_PDF_FILES = [
    Path("tests/data/pdf/picture_classification.pdf"),
    # Path("tests/data/pdf/beian.pdf")
]

TEST_OCR_ENGINES = ["rapid", "tesseract"]
# TEST_OCR_ENGINES = ["rapid", "tesseract", "easy", "mac"]
OUTPUT_DIR = Path("tests/output/pdf_ocr")

def setup_module(module):
    """模块级别的设置：创建输出目录"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def test_ocr_availability_check():
    """测试OCR引擎可用性检查功能"""
    print("\n🔍 测试OCR引擎真实可用性:")
    
    for engine in TEST_OCR_ENGINES:
        available, message = check_ocr_engine_availability(engine)
        status = "✅ 可用" if available else "❌ 不可用"
        print(f"  {engine}: {status}")
        
        if not available:
            print(f"    详情: {message}")

@pytest.mark.parametrize("pdf_file", TEST_PDF_FILES)
@pytest.mark.parametrize("ocr_engine", TEST_OCR_ENGINES)
def test_pdf_ocr_basic(pdf_file, ocr_engine):
    """测试不同OCR引擎的基本功能"""
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    # 首先检查引擎可用性
    available, error_message = check_ocr_engine_availability(ocr_engine)
    if not available:
        pytest.skip(f"OCR引擎 {ocr_engine} 不可用: {error_message}")
    
    # 如果可用，测试实际转换
    result = convert(
        content=str(pdf_file),
        content_type="file",
        pipeline="standard",
        ocr=ocr_engine,
        enable_formula_enrichment=True
    )
    
    # 检查是否返回了友好的错误信息
    if result.get("error") and result.get("error_type") == "OCREngineNotAvailable":
        pytest.fail(f"OCR引擎检查通过但转换失败: {result['message']}")
    
    assert "error" not in result, f"转换错误: {result.get('message', '')}"
    assert "markdown_content" in result
    assert result["markdown_content"].strip() != ""

@pytest.mark.parametrize("return_base64_images", [False, True])
def test_ocr_output_formats(return_base64_images):
    """测试OCR处理的不同输出格式"""
    # 选择一个适合OCR的PDF
    pdf_file = Path("tests/data/pdf/picture_classification.pdf")
    if not pdf_file.exists():
        pytest.skip(f"测试文件 {pdf_file} 不存在")
    
    # 使用rapid引擎（最可能可用的）
    ocr_engine = "rapid"
    
    # 检查引擎可用性
    available, error_message = check_ocr_engine_availability(ocr_engine)
    if not available:
        pytest.skip(f"OCR引擎 {ocr_engine} 不可用: {error_message}")
    
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

def test_migration_detection():
    """专门测试Intel到Apple Silicon迁移检测"""
    import platform
    import subprocess
    
    if platform.machine() != "arm64":
        pytest.skip("此测试仅适用于Apple Silicon Mac")
    
    print("\n🔧 检测Intel到Apple Silicon迁移问题:")
    
    # 检查brew架构
    try:
        result = subprocess.run(["brew", "--prefix"], capture_output=True, text=True)
        prefix = result.stdout.strip()
        if prefix == "/usr/local":
            print("  ⚠️  检测到Intel版本的Homebrew (/usr/local)")
            print("      建议重新安装Apple Silicon版本的Homebrew")
        elif prefix == "/opt/homebrew":
            print("  ✅ 使用Apple Silicon版本的Homebrew")
        else:
            print(f"  ❓ 未知的Homebrew路径: {prefix}")
    except FileNotFoundError:
        print("  ❌ 未找到Homebrew")
    
    # 检查Python架构
    print(f"  Python架构: {platform.machine()}")
    
    # 检查关键依赖的架构
    dependencies_to_check = ["tesseract"]
    for dep in dependencies_to_check:
        try:
            result = subprocess.run(["file", subprocess.run(["which", dep], 
                                   capture_output=True, text=True).stdout.strip()], 
                                   capture_output=True, text=True)
            if "arm64" in result.stdout:
                print(f"  ✅ {dep}: arm64架构")
            elif "x86_64" in result.stdout:
                print(f"  ⚠️  {dep}: x86_64架构（建议重新安装）")
            else:
                print(f"  ❓ {dep}: 未知架构")
        except:
            print(f"  ❌ {dep}: 未安装")
