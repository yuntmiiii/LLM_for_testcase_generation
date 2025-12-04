import uvicorn
import traceback
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prd_parser import FeishuDocParser
# 确保引用的是修改后的 model
from model import get_llm, build_content_parts, step_1_analyze_and_plan, step_2_generate_cases

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
        # 1. 解析飞书文档
        parser = FeishuDocParser(req.app_id, req.app_secret)
        parsed_data = parser.parse(req.doc_url)

        if not parsed_data:
            return {"status": "error", "message": "文档解析为空，请检查链接或权限"}

        print(f"解析成功，共 {len(parsed_data)} 个节点，正在发送给 LLM...")

        # 2. 提取图片映射 (前端展示 visual_evidence 需要用到)
        image_map = {}
        img_count = 0
        for node in parsed_data:
            if node['type'] == 'image':
                img_count += 1
                image_map[str(img_count)] = node['base64']

        # 3. 准备 LLM 上下文
        llm = get_llm()
        content_parts = build_content_parts(parsed_data)

        # 4. 执行 Step 1: 规划 (Plan)
        plan_result = await step_1_analyze_and_plan(llm, content_parts)

        # 5. 执行 Step 2: 生成 (Generate)
        case_result = await step_2_generate_cases(llm, content_parts, plan_result)

        # 6. 数据格式化 (Pydantic -> Dict)
        final_cases = [
            c.model_dump() if hasattr(c, 'model_dump') else c.dict()
            for c in case_result.cases
        ]
        final_analysis = [
            p.model_dump() if hasattr(p, 'model_dump') else p.dict()
            for p in plan_result.analysis_and_plan
        ]

        # 7. 【关键修复】构建符合前端预期的返回结构
        # 前端期待结构: { "status": "success", "data": { "cases": [], "analysis": [], "images": {} } }
        return {
            "status": "success",
            "data": {
                "cases": final_cases,
                "analysis": final_analysis,
                "images": image_map
            }
        }

    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"🔥 流程异常: {e}")
        return {
            "status": "error",
            "message": str(e),
            "traceback": error_msg
        }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)