import pytest
import os
import asyncio
import numpy as np
from typing import Dict, Any, List
import shutil

# 导入测试对象
from oculith.core.retriever import LanceRetriever

# 模拟LiteLLM类
class MockLiteLLM:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
    
    async def aembedding(self, texts, **kwargs):
        # 为每个文本生成随机向量作为嵌入
        if isinstance(texts, str):
            texts = [texts]
        
        class Response:
            def __init__(self, data):
                self.data = data
        
        data = []
        for text in texts:
            # 使用文本长度的哈希值作为随机种子以确保相同文本得到相同向量
            seed = hash(text) % 10000
            np.random.seed(seed)
            data.append({
                "embedding": np.random.random(384).tolist()
            })
        
        return Response(data)

# 替换导入
import sys
import importlib.util
from unittest.mock import patch

# 测试前的准备和清理
@pytest.fixture
def setup_and_cleanup():
    # 临时目录
    temp_dir = "./test_lance_db"
    os.makedirs(temp_dir, exist_ok=True)
    
    # 测试完成后清理
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

# 检索器测试
@pytest.mark.asyncio
async def test_lance_retriever(setup_and_cleanup, monkeypatch):
    temp_dir = setup_and_cleanup
    
    # 模拟LiteLLM
    monkeypatch.setattr("src.oculith.core.retriever.LiteLLM", MockLiteLLM)
    
    # 实例化检索器
    retriever = LanceRetriever(output_dir=temp_dir)
    
    # 关键修改：阻止索引创建
    monkeypatch.setattr(retriever, "ensure_index", lambda *args, **kwargs: None)
    
    # 测试数据
    texts = [
        "这是第一个测试文本",
        "这是第二个测试文本",
        "这是第三个测试文本，内容更长一些"
    ]
    
    metadatas = [
        {"file_id": "file1", "chunk_index": 0, "custom_field": "value1"},
        {"file_id": "file1", "chunk_index": 1, "custom_field": "value2"},
        {"file_id": "file2", "chunk_index": 0, "custom_field": "value3"}
    ]
    
    # 测试添加
    add_result = await retriever.add(
        texts=texts,
        collection_name="test_collection",
        user_id="test_user",
        metadatas=metadatas
    )
    
    assert add_result["success"] is True
    assert add_result["added"] == 3
    
    # 测试查询 - 全部
    query_results = await retriever.query(
        query_texts="测试文本",
        collection_name="test_collection"
    )
    
    assert len(query_results) == 1
    assert len(query_results[0]["results"]) > 0
    
    # 测试查询 - 按用户过滤
    user_query_results = await retriever.query(
        query_texts="测试文本",
        collection_name="test_collection",
        user_id="test_user"
    )
    
    assert len(user_query_results) == 1
    assert len(user_query_results[0]["results"]) > 0
    
    # 测试查询 - 按文件过滤
    file_query_results = await retriever.query(
        query_texts="测试文本",
        collection_name="test_collection",
        file_id="file1"
    )
    
    assert len(file_query_results) == 1
    assert len(file_query_results[0]["results"]) > 0
    
    # 测试删除 - 按文件ID
    delete_result = await retriever.delete(
        collection_name="test_collection",
        file_id="file1"
    )
    
    assert delete_result["success"] is True
    
    # 验证删除结果
    after_delete_results = await retriever.query(
        query_texts="测试文本",
        collection_name="test_collection"
    )
    
    # 应该只剩下file2的文档
    file_ids = [r["metadata"]["file_id"] for r in after_delete_results[0]["results"]]
    assert all(f == "file2" for f in file_ids)
    
    # 测试自定义过滤器
    custom_filter_results = await retriever.query(
        query_texts="测试文本",
        collection_name="test_collection",
        filter="length(text) > 10"
    )
    
    assert len(custom_filter_results[0]["results"]) > 0
    
    print("所有测试通过!")

if __name__ == "__main__":
    asyncio.run(pytest.main(["-xvs", __file__]))
