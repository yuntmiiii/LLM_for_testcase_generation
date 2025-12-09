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


import json
import traceback
from fastapi.responses import StreamingResponse


async def generate_stream_process(req: FeishuRequest):
    try:
        # --- 阶段 1: 解析文档 ---
        yield json.dumps({"type": "log", "message": "正在解析飞书文档..."}) + "\n"

        parser = FeishuDocParser(req.app_id, req.app_secret)
        parsed_data = parser.parse(req.doc_url)

        if not parsed_data:
            yield json.dumps({"type": "error", "message": "文档解析为空"}) + "\n"
            return

        image_map = {}
        img_count = 0
        for node in parsed_data:
            if node['type'] == 'image':
                img_count += 1
                image_map[str(img_count)] = node['base64']

        # 发送图片数据
        yield json.dumps({"type": "images", "data": image_map}) + "\n"

        # --- 阶段 2: AI 分析 (生成导图) ---
        yield json.dumps({"type": "log", "message": "正在进行 AI 深度分析与策略制定..."}) + "\n"

        llm = get_llm()
        content_parts = build_content_parts(parsed_data)

        # 执行 Step 1
        plan_result = await step_1_analyze_and_plan(llm, content_parts)

        final_analysis = [
            p.model_dump() if hasattr(p, 'model_dump') else p.dict()
            for p in plan_result.analysis_and_plan
        ]

        yield json.dumps({
            "type": "analysis",
            "data": final_analysis
        }) + "\n"

        yield json.dumps({"type": "log", "message": "策略已确认，正在生成详细测试用例..."}) + "\n"

        # 执行 Step 2
        case_result = await step_2_generate_cases(llm, content_parts, plan_result)

        final_cases = [
            c.model_dump() if hasattr(c, 'model_dump') else c.dict()
            for c in case_result.cases
        ]

        yield json.dumps({
            "type": "cases",
            "data": final_cases
        }) + "\n"

        yield json.dumps({"type": "done", "message": "生成完毕"}) + "\n"

    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"🔥 流程异常: {e}")
        yield json.dumps({"type": "error", "message": str(e)}) + "\n"


# 接口入口
@app.post("/generate_from_feishu")
async def generate_from_feishu(req: FeishuRequest):
    print(f"收到请求: {req.doc_url}")
    return StreamingResponse(generate_stream_process(req), media_type="application/x-ndjson")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)