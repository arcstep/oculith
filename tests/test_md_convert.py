import os
import shutil
import pytest
from pathlib import Path

from oculith.convert import convert
from oculith.config import get_document_path

# 测试数据路径
TEST_MD_PATH = Path("tests/data/md/duck.md")

@pytest.fixture
def cleanup_cache():
    """清理测试生成的缓存文件"""
    # 测试前先清理文件
    docid = "test_duck_md"
    doc_path = get_document_path(docid)
    parquet_path = doc_path.with_suffix('.parquet')
    if parquet_path.exists():
        parquet_path.unlink()
    # 确保目录存在
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 测试执行
    yield
    
    # 测试后再次清理
    if parquet_path.exists():
        parquet_path.unlink()


def test_convert_markdown_basic(cleanup_cache):
    """测试基本的Markdown转换功能"""
    # 确保测试文件存在
    assert TEST_MD_PATH.exists(), f"测试文件 {TEST_MD_PATH} 不存在"
    
    # 获取文件内容
    with open(TEST_MD_PATH, "r", encoding="utf-8") as f:
        md_content = f.read()
    
    # 执行转换，使用固定的document_id以便清理
    result = convert(
        content=str(TEST_MD_PATH),
        content_type="file",
        document_id="test_duck_md"
    )
    
    # 检查转换结果
    assert "document_id" in result
    assert "markdown_content" in result
    assert result["document_id"] == "test_duck_md"
    assert result["from_cache"] == False
    
    # 检查内容是否基本匹配
    # 注意：转换后的内容可能会有格式调整，所以我们只检查关键内容
    # 假设duck.md中包含"duck"这个词
    assert "duck" in result["markdown_content"].lower()


def test_convert_markdown_cache(cleanup_cache):
    """测试缓存机制是否正常工作"""
    # 第一次转换
    result1 = convert(
        content=str(TEST_MD_PATH),
        content_type="file",
        document_id="test_duck_md"
    )
    assert result1["from_cache"] == False
    
    # 第二次转换，应该使用缓存
    result2 = convert(
        content=str(TEST_MD_PATH),
        content_type="file",
        document_id="test_duck_md"
    )
    assert result2["from_cache"] == True
    
    # 强制重新转换
    result3 = convert(
        content=str(TEST_MD_PATH),
        content_type="file",
        document_id="test_duck_md",
        force_convert=True
    )
    assert result3["from_cache"] == False


def test_convert_markdown_embedded(cleanup_cache):
    """测试嵌入图片的Markdown转换"""
    result = convert(
        content=str(TEST_MD_PATH),
        content_type="file",
        document_id="test_duck_md",
        return_type="markdown_embedded"
    )
    
    # Markdown文件通常不包含图片，所以我们只需要检查输出格式即可
    assert "markdown_content" in result
    # 因为我们请求嵌入图片，但可能文件中没有图片
    # 所以只检查基本结构，不检查data:image前缀


def test_convert_chunks(cleanup_cache):
    """测试Markdown切片功能"""
    # 设置一个较小的chunk_size，以确保会产生多个切片
    result = convert(
        content=str(TEST_MD_PATH),
        content_type="file",
        document_id="test_duck_md",
        return_type="chunks",
        chunker_config={
            "max_chunk_size": 200,  # 较小的块大小
            "overlap": 50
        }
    )
    
    # 检查是否返回了切片
    assert "chunks" in result
    assert isinstance(result["chunks"], list)
    
    # 如果文档足够大，应该有至少一个切片
    assert len(result["chunks"]) > 0
    
    # 检查切片格式
    first_chunk = result["chunks"][0]
    assert "content" in first_chunk
    assert "metadata" in first_chunk
    
    # 检查元数据
    metadata = first_chunk["metadata"]
    assert "index" in metadata
    assert "total_chunks" in metadata
    assert metadata["document_type"] == "markdown"


def test_convert_file_type_detection(cleanup_cache):
    """测试文件类型自动检测功能"""
    # 使用auto模式应该能正确识别.md文件
    result = convert(
        content=str(TEST_MD_PATH),
        content_type="auto",  # 自动检测
        document_id="test_duck_md"
    )
    
    assert "markdown_content" in result
    assert result["from_cache"] == False
