from starlette.middleware.cors import CORSMiddleware

import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List

from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

import prompts

load_dotenv()

app = FastAPI(title="自动测试用例生成服务")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有域名（生产环境建议指定具体域名，如 "http://localhost:3000"）
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有 HTTP 方法（包括 OPTIONS、POST）
    allow_headers=["*"],  # 允许所有请求头
)

class PRDRequest(BaseModel):
    content: str = Field(..., description="产品需求文档(PRD)的文本内容")

class TestCase(BaseModel):
    module: str = Field(description="功能模块名称")
    title: str = Field(description="用例标题")
    pre_condition: str = Field(description="前置条件")
    steps: List[str] = Field(description="测试步骤列表")
    expected_result: str = Field(description="预期结果")

# 定义最终返回给前端的结构 (包含用例列表)
class TestCasesOutput(BaseModel):
    cases: List[TestCase]

@app.post("/generate")
async def generate_cases(req: PRDRequest):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="服务器未配置 OPENAI_API_KEY，请检查 .env 文件")
    api_key = os.getenv("ARK_API_KEY")
    model_endpoint = 'ep-20251120150050-5x4qz'
    try:
        llm = ChatOpenAI(
            api_key=api_key,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            model=model_endpoint,
            temperature=0,
            timeout=300,
            max_retries=1,
            http_client=None 
        )
        parser = JsonOutputParser(pydantic_object=TestCasesOutput)

        prompt = ChatPromptTemplate.from_messages([
            ("system", prompts.SYSTEM_PROMPT),
            ("user", prompts.USER_TEMPLATE)
        ])

        chain = prompt | llm | parser

        result = await chain.ainvoke({
            "format_instructions": parser.get_format_instructions(),
            "prd_text": req.content.strip()
        })
        print(result)
        return {"status": "success", "data": result}

    except HTTPException as e:
        raise e
    except Exception as e:
        error_msg = f"用例生成失败：{str(e)}"
        print(f"生成出错: {error_msg}")
        return {"status": "error", "message": error_msg}

if __name__ == "__main__":
    print("🚀 测试用例生成服务正在启动...")
    print("📡 监听地址: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)