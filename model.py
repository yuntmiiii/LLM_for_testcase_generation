# model.py
import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv
import prompts

load_dotenv()

API_KEY = os.getenv("ARK_API_KEY")
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_ENDPOINT = "ep-20251125155621-z8fhp"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
SYSTEM_PROMPT = prompts.SYSTEM_PROMPT


def clean_json_string(s):
    s = re.sub(r"```json\s*", "", s)
    s = re.sub(r"```", "", s)
    return s.strip()


def normalize_structure(data):
    # 清洗模型输出
    raw_list = []

    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):

        for key in ["cases", "test_cases", "测试用例", "测试用例列表", "用例列表", "content"]:
            if key in data and isinstance(data[key], list):
                raw_list = data[key]
                break

        if not raw_list and "title" in data:
            raw_list = [data]

    normalized_cases = []
    for item in raw_list:
        new_item = {}

        new_item["module"] = item.get("module") or item.get("模块") or item.get("功能模块") or item.get(
            "所属模块") or "默认模块"

        new_item["title"] = item.get("title") or item.get("测试标题") or item.get("用例标题") or item.get(
            "测试点") or item.get("用例名称") or "未命名用例"

        new_item["pre_condition"] = item.get("pre_condition") or item.get("前置条件") or item.get("预置条件") or "无"
        steps = item.get("steps") or item.get("操作步骤") or item.get("测试步骤") or item.get("步骤") or []

        if isinstance(steps, str):
            steps = [s.strip() for s in steps.split('\n') if s.strip()]
        new_item["steps"] = steps
        new_item["expected_result"] = item.get("expected_result") or item.get("预期结果") or item.get("期待结果") or "无"

        normalized_cases.append(new_item)

    return {"cases": normalized_cases}


async def generate_test_cases_llm(parsed_data: list):
    if not API_KEY:
        raise ValueError("未配置 ARK_API_KEY")

    user_content = [{"type": "text", "text": "请分析以下PRD文档内容，输出JSON格式的测试用例："}]

    img_count = 0
    for node in parsed_data:
        if node['type'] == 'text':
            user_content.append({"type": "text", "text": node['content']})
        elif node['type'] == 'image':
            img_count += 1
            user_content.append({"type": "text", "text": f"\n[参考图 {img_count}]\n"})
            user_content.append({
                "type": "image_url",
                "image_url": {"url": node['base64']}
            })

    print(f"正在调用 LLM (Endpoint: {MODEL_ENDPOINT})...")
    # print(user_content)
    try:
        response = client.chat.completions.create(
            model=MODEL_ENDPOINT,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            temperature=0.1,
            max_tokens=4096,
            response_format={"type": "json_object"}
        )

        raw_content = response.choices[0].message.content
        print("LLM 原始返回:", raw_content)
        clean_content = clean_json_string(raw_content)
        json_result = json.loads(clean_content)
        final_result = normalize_structure(json_result)

        return final_result

    except json.JSONDecodeError:
        print("JSON 解析失败")
        return {"cases": []}
    except Exception as e:
        raise e