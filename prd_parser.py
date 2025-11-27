import requests
import json
import base64
import re
import io
from PIL import Image


class FeishuDocParser:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = "https://open.feishu.cn/open-apis"
        self._tenant_access_token = ""

    def _get_token(self):
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        data = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        resp = requests.post(url, headers=headers, json=data)
        if resp.status_code == 200:
            self._tenant_access_token = resp.json().get("tenant_access_token")
        else:
            raise Exception(f"获取Token失败: {resp.text}")

    def _get_headers(self):
        if not self._tenant_access_token:
            self._get_token()
        return {
            "Authorization": f"Bearer {self._tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }

    def _download_image_as_base64(self, file_token):
        # 压缩过大图片
        if not file_token: return None
        url = f"{self.base_url}/drive/v1/medias/{file_token}/download"

        try:
            resp = requests.get(url, headers=self._get_headers(), stream=True)
            if resp.status_code == 200:
                image = Image.open(io.BytesIO(resp.content))
                width, height = image.size
                total_pixels = width * height
                MAX_PIXELS = 30 * 1000 * 1000

                if total_pixels > MAX_PIXELS:
                    scale_factor = (MAX_PIXELS / total_pixels) ** 0.5
                    new_width = int(width * scale_factor)
                    new_height = int(height * scale_factor)
                    print(f"⚠️ 发现超大图片 ({width}x{height})，正在压缩至 ({new_width}x{new_height})...")
                    image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                if image.mode in ("RGBA", "P"):
                    image = image.convert("RGB")

                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=85)
                buffer.seek(0)

                b64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
                return f"data:image/jpeg;base64,{b64_data}"

        except Exception as e:
            print(f"图片处理失败 ({file_token}): {e}")
            pass
        return None

    def _get_real_doc_token(self, url):
        token = url
        if "feishu.cn" in url:
            if '/wiki/' in url:
                token = url.split('/wiki/')[-1].split('?')[0]
                print(f"检测到 Wiki 链接，尝试转换 Token: {token} ...")
                try:
                    api_url = f"{self.base_url}/wiki/v2/spaces/get_node?token={token}"
                    resp = requests.get(api_url, headers=self._get_headers()).json()
                    if resp.get("code") == 0:
                        real_token = resp["data"]["node"]["obj_token"]
                        print(f"--> 转换成功: {real_token}")
                        return real_token
                except Exception as e:
                    print(f"Wiki转换异常(可忽略，尝试直接解析): {e}")
            elif '/docx/' in url:
                token = url.split('/docx/')[-1].split('?')[0]

        return token

    def _extract_text_smart(self, elements):
        text_content = ""
        for el in elements:
            if 'text_run' in el:
                text_content += el['text_run'].get('content', '')
            elif 'mention_doc' in el:
                text_content += f"[{el['mention_doc'].get('token', '文档')}]"
            elif 'equation' in el:
                text_content += f"${el['equation'].get('content', '')}$"
        return text_content

    def parse(self, doc_url):
        doc_id = self._get_real_doc_token(doc_url)
        print(f"正在解析文档 ID: {doc_id} ...")
        blocks_url = f"{self.base_url}/docx/v1/documents/{doc_id}/blocks"
        all_blocks = []
        params = {"page_size": 500}

        while True:
            resp = requests.get(blocks_url, headers=self._get_headers(), params=params)
            data = resp.json()
            if data.get("code") != 0:
                raise Exception(f"API请求失败: {data} (请检查是否拥有 wiki:read 或 docx:read 权限)")
            items = data["data"]["items"]
            all_blocks.extend(items)
            if not data["data"].get("has_more"): break
            params["page_token"] = data["data"]["page_token"]

        parsed_results = []
        list_counter = 0

        TEXT_KEYS = [
            "text", "heading1", "heading2", "heading3", "heading4", "heading5",
            "ordered", "bullet", "quote", "todo", "code", "callout"
        ]

        print(f"获取到 {len(all_blocks)} 个块，开始解析...")

        for block in all_blocks:
            b_type = block.get("block_type")
            # 图片处理
            if b_type == 27:
                img_token = block.get("image", {}).get("token")
                if img_token:
                    print(f"发现图片: {img_token}")
                    b64_img = self._download_image_as_base64(img_token)
                    if b64_img:
                        parsed_results.append({
                            "type": "image",
                            "base64": b64_img,
                            "token": img_token
                        })
                continue

            # 表格处理
            if b_type == 31:
                parsed_results.append({"type": "text", "content": "\n[表格内容]\n"})
                continue

            found_data = None
            found_key = None

            for key in TEXT_KEYS:
                if block.get(key):
                    found_data = block.get(key)
                    found_key = key
                    break

            if found_data and "elements" in found_data:
                text_content = self._extract_text_smart(found_data["elements"])

                if text_content.strip() or found_key == 'code':
                    prefix = ""

                    if "heading" in found_key:
                        level = int(found_key[-1])
                        prefix = "#" * level + " "
                        list_counter = 0

                    elif found_key == "ordered":
                        list_counter += 1
                        prefix = f"{list_counter}. "

                    elif found_key == "bullet":
                        prefix = "- "
                        list_counter = 0

                    elif found_key == "quote":
                        prefix = "> "
                        list_counter = 0

                    elif found_key == "todo":
                        prefix = "[ ] "
                        list_counter = 0

                    else:
                        list_counter = 0

                    parsed_results.append({
                        "type": "text",
                        "content": prefix + text_content
                    })

        return parsed_results


if __name__ == "__main__":
    APP_ID = "cli_a9aea23fa238dceb"
    APP_SECRET = "fTU0bjnhi6LNFGG4IaSaKfeuPzXgRaWT"
    DOC_URL = "https://vcn182f81pca.feishu.cn/wiki/JceZwDKtviOsgekeOOTcEhHjnvb"

    try:
        parser = FeishuDocParser(APP_ID, APP_SECRET)
        results = parser.parse(DOC_URL)
        print(f"\n✅ 解析完成! 共获取 {len(results)} 条有效内容。\n")
        print("--- 文档内容概览 ---")
        for i, node in enumerate(results):
            if node['type'] == 'text':
                print(f"{node['content']}")
            elif node['type'] == 'image':
                print(f"[图片] (Base64长度: {len(node['base64'])})")

    except Exception as e:
        print(f"发生错误: {e}")