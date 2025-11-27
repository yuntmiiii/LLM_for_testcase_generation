import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prd_parser import FeishuDocParser
from model import generate_test_cases_llm

app = FastAPI(title="基于LLM的测试用例生成")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class FeishuRequest(BaseModel):
    doc_url: str = Field(..., description="飞书文档链接")
    app_id: str = Field(..., description="飞书 App ID")
    app_secret: str = Field(..., description="飞书 App Secret")


@app.post("/generate_from_feishu")
async def generate_from_feishu(req: FeishuRequest):
    print(f"收到请求: {req.doc_url}")

    try:
        parser = FeishuDocParser(req.app_id, req.app_secret)
        parsed_data = parser.parse(req.doc_url)

        if not parsed_data:
            return {"status": "error", "message": "文档解析为空，请检查链接或权限"}
        print(f"解析成功，共 {len(parsed_data)} 个节点，正在发送给 LLM...")
        result_dict = await generate_test_cases_llm(parsed_data)
        return {
            "status": "success",
            "data": result_dict
        }

    except Exception as e:
        print(f"服务内部错误: {str(e)}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)