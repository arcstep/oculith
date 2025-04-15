# .env 文件配置示例
# OPENAI_IMITATORS=OPENAI,LOCALAI,BAIDU
# OPENAI_API_KEY=sk-xxx
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_COMPLETION_MODEL=gpt-3.5-turbo,gpt-4
# OPENAI_EMBEDDING_MODEL=text-embedding-ada-002
# 
# LOCALAI_API_KEY=
# LOCALAI_BASE_URL=http://localhost:8080/v1
# LOCALAI_COMPLETION_MODEL=llama2,orca-mini
# LOCALAI_EMBEDDING_MODEL=embedding-model
#
# BAIDU_API_KEY=xxx
# BAIDU_BASE_URL=https://api.baidu.com/v1
# BAIDU_COMPLETION_MODEL=ernie-bot-4,ernie-bot
# BAIDU_EMBEDDING_MODEL=embedding-v1

# 创建默认LiteLLM实例(使用第一个可用的imitator)
#!/usr/bin/env python
"""
文档处理服务的主入口点
"""
import logging
import asyncio
import os

from typing import Optional, List
from pathlib import Path

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("illufly_docling")

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "False"

from oculith.core.litellm import LiteLLM, init_litellm

init_litellm(cache_dir=".db/litellm_cache")
llm = LiteLLM()

# 异步调用
async def main():
    # 获取所有可用的imitators和模型
    imitators = llm.list_imitators()
    print(imitators)

    # 使用默认设置进行completion
    response = llm.completion("我是一个测试，你直接返回一句话说明你的模型名称即可", imitator="OPENAI")
    print(response)

    response = await llm.acompletion("我是一个异步请求测试，你直接返回一句话说明你的模型名称即可")
    print(response)

    # 文本嵌入
    embedding_llm = LiteLLM(model_type="embedding")
    vectors = embedding_llm.embedding(["这是一段测试文本"])
    print(str(vectors)[:300])

asyncio.run(main())