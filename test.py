import requests
import json
import time

APP_ID = "cli_a9aea23fa238dceb"
APP_SECRET = "fTU0bjnhi6LNFGG4IaSaKfeuPzXgRaWT"
DOC_URL = "https://vcn182f81pca.feishu.cn/wiki/JceZwDKtviOsgekeOOTcEhHjnvb"

def dump_entire_doc():
    print("1. 正在获取 Access Token...")
    auth_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(auth_url, json={"app_id": APP_ID, "app_secret": APP_SECRET})
    if resp.status_code != 200:
        print(f"鉴权失败: {resp.text}")
        return
    token = resp.json().get("tenant_access_token")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    real_doc_token = ""
    if "/wiki/" in DOC_URL:
        wiki_token = DOC_URL.split("/wiki/")[-1].split("?")[0]
        print(f"2. 检测到 Wiki Token ({wiki_token})，正在转换...")
        wiki_api = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token={wiki_token}"
        wiki_resp = requests.get(wiki_api, headers=headers).json()
        if wiki_resp.get("code") == 0:
            real_doc_token = wiki_resp["data"]["node"]["obj_token"]
            print(f"   -> 转换成功，真实文档 Token: {real_doc_token}")
        else:
            print(f"   -> Wiki 转换失败: {wiki_resp}")
            return
    else:
        real_doc_token = DOC_URL.split("/docx/")[-1].split("?")[0]
        print(f"2. 使用 Doc Token: {real_doc_token}")

    print("3. 开始拉取所有 Block 数据...")
    blocks_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{real_doc_token}/blocks"
    all_blocks = []
    page_token = None

    while True:
        params = {"page_size": 500}
        if page_token: params["page_token"] = page_token

        r = requests.get(blocks_url, headers=headers, params=params)
        data = r.json()

        if data.get("code") != 0:
            print(f"API 请求出错: {data}")
            break

        items = data["data"]["items"]
        all_blocks.extend(items)
        print(f"   -> 已获取 {len(items)} 个块...")

        if not data["data"].get("has_more"):
            break
        page_token = data["data"]["page_token"]

    print(f"4. 拉取完成，共 {len(all_blocks)} 个 Block。")

    filename = "debug_feishu_doc.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(all_blocks, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 原始数据已保存到: {filename}")
    print("请打开该文件，Ctrl+F 搜索你没解析出来的文字（比如 '输入登录账号'）。")
    print("查看它所属的 json 对象，重点看 'block_type' 是多少，以及文字藏在哪个 key 下面。")


if __name__ == "__main__":
    dump_entire_doc()