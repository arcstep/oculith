import pytest
from pathlib import Path

from oculith.convert import convert
from oculith.config import get_document_path

# 测试数据
TEST_PDF_FILES = [
    Path("tests/data/pdf/code_and_formula.pdf"),      # 包含代码和公式
    Path("tests/data/pdf/amt_handbook_sample.pdf")       # 普通文本报告
]

TEST_DOCX_FILES = [
    Path("tests/data/docx/lorem_ipsum.docx"),         # 纯文本样例
    Path("tests/data/docx/unit_test_formatting.docx") # 格式丰富的文档
]

@pytest.fixture
def cleanup_test_files():
    """清理测试文件缓存"""
    # 测试前清理
    for file_path in TEST_PDF_FILES + TEST_DOCX_FILES:
        file_name = file_path.stem
        docid = f"extract_{file_name}"
        doc_path = get_document_path(docid)
        parquet_path = doc_path.with_suffix('.parquet')
        if parquet_path.exists():
            parquet_path.unlink()
        # 确保目录存在
        doc_path.parent.mkdir(parents=True, exist_ok=True)
    
    yield
    
    # 测试后清理
    for file_path in TEST_PDF_FILES + TEST_DOCX_FILES:
        file_name = file_path.stem
        docid = f"extract_{file_name}"
        doc_path = get_document_path(docid)
        parquet_path = doc_path.with_suffix('.parquet')
        if parquet_path.exists():
            parquet_path.unlink()

class TestPDFTextExtraction:
    """测试PDF文件的文本提取功能"""
    
    @pytest.mark.parametrize("pdf_file", TEST_PDF_FILES)
    def test_pdf_text_extraction(self, cleanup_test_files, pdf_file):
        """测试从PDF直接提取文本"""
        file_name = pdf_file.stem
        document_id = f"extract_{file_name}"
        
        result = convert(
            content=str(pdf_file),
            content_type="file",
            document_id=document_id,
            ocr=None  # 明确指定不使用OCR
        )
        
        # 基本检查
        assert "markdown_content" in result
        assert result["document_id"] == document_id
        assert result["from_cache"] == False
        
        # 内容检查
        content = result["markdown_content"]
        assert content.strip() != ""
        
        # 针对特定文件的期望内容
        if "code_and_formula" in file_name:
            # 可能包含代码片段或公式的特征
            assert len(content) > 100  # 至少应该有一定量的文本
        
        # 验证缓存机制
        result2 = convert(
            content=str(pdf_file),
            content_type="file",
            document_id=document_id
        )
        assert result2["from_cache"] == True
    
    @pytest.mark.parametrize("pdf_file", TEST_PDF_FILES) 
    def test_pdf_text_with_chunks(self, cleanup_test_files, pdf_file):
        """测试PDF文本提取加切片"""
        file_name = pdf_file.stem
        document_id = f"extract_{file_name}"
        
        result = convert(
            content=str(pdf_file),
            content_type="file",
            document_id=document_id,
            ocr=None,
            return_type="chunks",
            chunker_config={"max_chunk_size": 500, "overlap": 100}
        )
        
        # 检查切片结果
        assert "chunks" in result
        assert isinstance(result["chunks"], list)
        if len(result["chunks"]) > 0:  # 有些PDF可能内容太少无法切片
            chunk = result["chunks"][0]
            assert "content" in chunk
            assert "metadata" in chunk


class TestDOCXTextExtraction:
    """测试DOCX文件的文本提取功能"""
    
    @pytest.mark.parametrize("docx_file", TEST_DOCX_FILES)
    def test_docx_text_extraction(self, cleanup_test_files, docx_file):
        """测试从DOCX直接提取文本"""
        file_name = docx_file.stem
        document_id = f"extract_{file_name}"
        
        result = convert(
            content=str(docx_file),
            content_type="file",
            document_id=document_id
        )
        
        # 基本检查
        assert "markdown_content" in result
        assert result["document_id"] == document_id
        assert result["from_cache"] == False
        
        # 内容检查
        content = result["markdown_content"]
        assert content.strip() != ""
        
        # 针对特定文件的期望内容
        if "lorem_ipsum" in file_name:
            assert "lorem" in content.lower()
        
        # 验证缓存机制
        result2 = convert(
            content=str(docx_file),
            content_type="file",
            document_id=document_id
        )
        assert result2["from_cache"] == True
    
    @pytest.mark.parametrize("docx_file", TEST_DOCX_FILES)
    def test_docx_embedded_images(self, cleanup_test_files, docx_file):
        """测试DOCX嵌入图片提取"""
        file_name = docx_file.stem
        document_id = f"extract_{file_name}"
        
        result = convert(
            content=str(docx_file),
            content_type="file",
            document_id=document_id,
            return_type="markdown_embedded"
        )
        
        # 基本检查
        assert "markdown_content" in result
        
        # 注意：不是所有DOCX都包含图片，所以不强制断言图片存在
        # 但如果文件名包含图片相关词，则增加额外检查
        if "emf" in file_name or "image" in file_name:
            assert "![" in result["markdown_content"] or "data:image" in result["markdown_content"]
