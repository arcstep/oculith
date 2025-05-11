import pytest
from pathlib import Path

from oculith.convert import convert
from oculith.config import get_document_path

# 测试数据 - 选择更适合OCR测试的文件
TEST_PDF_FILES = [
    Path("tests/data/pdf/picture_classification.pdf")
]

TEST_IMAGES = [
    Path("tests/data/images/beian.png")
]

@pytest.fixture
def cleanup_test_files():
    """清理测试文件缓存"""
    # 测试前清理
    for file_path in TEST_PDF_FILES + TEST_IMAGES   :
        file_name = file_path.stem
        # 同时清理OCR和非OCR的缓存
        for prefix in ["ocr", "non_ocr"]:
            docid = f"{prefix}_{file_name}"
            doc_path = get_document_path(docid)
            parquet_path = doc_path.with_suffix('.parquet')
            if parquet_path.exists():
                parquet_path.unlink()
            # 确保目录存在
            doc_path.parent.mkdir(parents=True, exist_ok=True)
    
    yield
    
    # 测试后清理
    for file_path in TEST_PDF_FILES + TEST_IMAGES:
        file_name = file_path.stem
        # 同时清理OCR和非OCR的缓存
        for prefix in ["ocr", "non_ocr"]:
            docid = f"{prefix}_{file_name}"
            doc_path = get_document_path(docid)
            parquet_path = doc_path.with_suffix('.parquet')
            if parquet_path.exists():
                parquet_path.unlink()

class TestPDFOCRExtraction:
    """测试PDF文件的OCR文本提取"""
    
    @pytest.mark.parametrize("pdf_file", TEST_PDF_FILES)
    def test_tesseract_ocr_extraction(self, cleanup_test_files, pdf_file):
        """测试OCR从PDF提取文本"""
        file_name = pdf_file.stem
        ocr_id = f"ocr_{file_name}"
        
        # 使用OCR处理
        ocr_result = convert(
            content=str(pdf_file),
            content_type="file",
            document_id=ocr_id,
            ocr="tesseract"
        )
        
        # 基本检查
        assert "markdown_content" in ocr_result
        assert ocr_result["document_id"] == ocr_id
        assert ocr_result["from_cache"] == False
        
        # 内容检查
        ocr_content = ocr_result["markdown_content"]
        
        assert ocr_content.strip() != ""
        assert len(ocr_content) > 0
    
    @pytest.mark.parametrize("pdf_file", TEST_PDF_FILES)
    def test_rapid_ocr_extraction(self, cleanup_test_files, pdf_file):
        """测试OCR从PDF提取文本"""
        file_name = pdf_file.stem
        ocr_id = f"ocr_{file_name}"
        
        # 使用OCR处理
        ocr_result = convert(
            content=str(pdf_file),
            content_type="file",
            document_id=ocr_id,
            ocr="rapid"
        )
        
        # 基本检查
        assert "markdown_content" in ocr_result
        assert ocr_result["document_id"] == ocr_id
        assert ocr_result["from_cache"] == False
        
        # 内容检查
        ocr_content = ocr_result["markdown_content"]
        
        assert ocr_content.strip() != ""
        assert len(ocr_content) > 0

    @pytest.mark.parametrize("pdf_file", TEST_PDF_FILES)
    def test_mac_ocr_extraction(self, cleanup_test_files, pdf_file):
        """测试OCR从PDF提取文本"""
        file_name = pdf_file.stem
        ocr_id = f"ocr_{file_name}"
        
        # 使用OCR处理
        ocr_result = convert(
            content=str(pdf_file),
            content_type="file",
            document_id=ocr_id,
            ocr="mac"
        )
        
        # 基本检查
        assert "markdown_content" in ocr_result
        assert ocr_result["document_id"] == ocr_id
        assert ocr_result["from_cache"] == False
        
        # 内容检查
        ocr_content = ocr_result["markdown_content"]
        
        assert ocr_content.strip() != ""
        assert len(ocr_content) > 0

    @pytest.mark.parametrize("pdf_file", TEST_PDF_FILES)
    def test_easy_ocr_extraction(self, cleanup_test_files, pdf_file):
        """测试OCR从PDF提取文本"""
        file_name = pdf_file.stem
        ocr_id = f"ocr_{file_name}"
        
        # 使用OCR处理
        ocr_result = convert(
            content=str(pdf_file),
            content_type="file",
            document_id=ocr_id,
            ocr="easy"
        )
        
        # 基本检查
        assert "markdown_content" in ocr_result
        assert ocr_result["document_id"] == ocr_id
        assert ocr_result["from_cache"] == False
        
        # 内容检查
        ocr_content = ocr_result["markdown_content"]
        
        assert ocr_content.strip() != ""
        assert len(ocr_content) > 0

class TestImageOCRExtraction:
    """测试图片的OCR文本提取"""
    
    @pytest.mark.parametrize("image_file", TEST_IMAGES)
    def test_tesseract_ocr_extraction(self, cleanup_test_files, image_file):
        """测试OCR从图片提取文本"""
        file_name = image_file.stem
        ocr_id = f"ocr_{file_name}"
        
        # 使用OCR处理
        ocr_result = convert(
            content=str(image_file),
            content_type="file",
            document_id=ocr_id,
            ocr="tesseract"
        )
        
        # 基本检查
        assert "markdown_content" in ocr_result
        assert ocr_result["document_id"] == ocr_id
        assert ocr_result["from_cache"] == False
        
        # 内容检查
        ocr_content = ocr_result["markdown_content"]
        
        assert ocr_content.strip() != ""
        assert len(ocr_content) > 0
    
    @pytest.mark.parametrize("image_file", TEST_IMAGES)
    def test_rapid_ocr_extraction(self, cleanup_test_files, image_file):
        """测试OCR从图片提取文本"""
        file_name = image_file.stem
        ocr_id = f"ocr_{file_name}"
        
        # 使用OCR处理
        ocr_result = convert(
            content=str(image_file),
            content_type="file",
            document_id=ocr_id,
            ocr="rapid"
        )
        
        # 基本检查
        assert "markdown_content" in ocr_result
        assert ocr_result["document_id"] == ocr_id
        assert ocr_result["from_cache"] == False
        
        # 内容检查
        ocr_content = ocr_result["markdown_content"]
        
        assert ocr_content.strip() != ""
        assert len(ocr_content) > 0

    @pytest.mark.parametrize("image_file", TEST_IMAGES)
    def test_mac_ocr_extraction(self, cleanup_test_files, image_file):
        """测试OCR从图片提取文本"""
        file_name = image_file.stem
        ocr_id = f"ocr_{file_name}"
        
        # 使用OCR处理
        ocr_result = convert(
            content=str(image_file),
            content_type="file",
            document_id=ocr_id,
            ocr="mac"
        )
        
        # 基本检查
        assert "markdown_content" in ocr_result
        assert ocr_result["document_id"] == ocr_id
        assert ocr_result["from_cache"] == False
        
        # 内容检查
        ocr_content = ocr_result["markdown_content"]
        
        assert ocr_content.strip() != ""
        assert len(ocr_content) > 0

    @pytest.mark.parametrize("image_file", TEST_IMAGES)
    def test_easy_ocr_extraction(self, cleanup_test_files, image_file):
        """测试OCR从图片提取文本"""
        file_name = image_file.stem
        ocr_id = f"ocr_{file_name}"
        
        # 使用OCR处理
        ocr_result = convert(
            content=str(image_file),
            content_type="file",
            document_id=ocr_id,
            ocr="easy"
        )
        
        # 基本检查
        assert "markdown_content" in ocr_result
        assert ocr_result["document_id"] == ocr_id
        assert ocr_result["from_cache"] == False
        
        # 内容检查
        ocr_content = ocr_result["markdown_content"]
        
        assert ocr_content.strip() != ""
        assert len(ocr_content) > 0
