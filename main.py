from typing import Optional
import uvicorn
import traceback
import json
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from prd_parser import FeishuDocParser
from file_parser import parse_uploaded_file  # 【新增导入】
from model import get_llm, build_content_parts, step_1_analyze_and_plan, step_2_generate_cases
from db import save_result, get_result_by_key, init_db

try:
    init_db()
except Exception as e:
    print(f"Database initialization failed: {e}")

app = FastAPI(title="基于LLM的测试用例生成")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CaseSaveRequest(BaseModel):
    final_json: dict = Field(..., description="最终生成的测试用例和分析的 JSON 结构")


async def generate_stream_process(
        input_mode: str,
        doc_url: str,
        raw_content: str,
        app_id: str,
        app_secret: str,
        uploaded_file: UploadFile
):
    try:
        parsed_data = []

        if input_mode == 'link':
            yield json.dumps({"type": "log", "message": "正在解析飞书文档..."}) + "\n"
            if not doc_url:
                raise ValueError("请提供飞书文档链接")
            if not app_id or not app_secret:
                raise ValueError("请提供飞书 App ID 和 App Secret")

            parser = FeishuDocParser(app_id, app_secret)
            parsed_data = parser.parse(doc_url)

        elif input_mode == 'text':
            yield json.dumps({"type": "log", "message": "正在解析粘贴的文本内容..."}) + "\n"
            if not raw_content:
                raise ValueError("请粘贴 PRD 文本内容")

            parsed_data = FeishuDocParser.parse_text(raw_content)

        elif input_mode == 'file':
            yield json.dumps({"type": "log", "message": f"正在解析上传的文件: {uploaded_file.filename}..."}) + "\n"
            if not uploaded_file:
                raise ValueError("未接收到上传的文件")

            text_content = await parse_uploaded_file(uploaded_file)

            if not text_content:
                raise ValueError("文件内容为空或无法提取")

            # 将提取的文本转换为 LLM 统一格式
            parsed_data = FeishuDocParser.parse_text(text_content)

        else:
            raise ValueError(f"不支持的输入模式: {input_mode}")

        if not parsed_data:
            yield json.dumps({"type": "error", "message": "解析内容为空，请检查输入"}) + "\n"
            return


        image_map = {}
        img_count = 0
        for node in parsed_data:
            if node['type'] == 'image':
                img_count += 1
                image_map[str(img_count)] = node['base64']


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


@app.post("/generate_from_feishu")
async def generate_from_feishu(
    input_mode: str = Form("link"),
    doc_url: str = Form(None),
    raw_content: str = Form(None),
    app_id: str = Form(None),
    app_secret: str = Form(None),
    uploaded_file: Optional[UploadFile] = File(None)
):
    print(f"收到请求，模式: {input_mode}")
    return StreamingResponse(
        generate_stream_process(
            input_mode, doc_url, raw_content, app_id, app_secret, uploaded_file
        ),
        media_type="application/x-ndjson"
    )


@app.post("/save_result")
async def save_case_result(req: CaseSaveRequest):
    try:
        # url 返回 '/?key={unique_key}'
        unique_key = save_result(req.final_json)
        return {"key": unique_key, "url": f"/?key={unique_key}"}
    except Exception as e:
        print(f"🔥 保存异常: {e}")
        return {"message": "保存失败", "error": str(e)}, 500


@app.get("/load/{key}")
async def load_case_result(key: str):
    result = get_result_by_key(key)
    if result:
        return result
    else:
        return {"message": "未找到对应的测试用例结果"}, 404


app.mount("/static", StaticFiles(directory="."), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    try:
        with open("test_case_web.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Error: test_case_web.html not found.</h1>", status_code=404)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)