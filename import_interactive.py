import os
import json
import requests

TOKEN = "a766805314bc8234cdee771ac14421f6"
BASE_URL = "https://modao.cc"
IMPORT_ENDPOINT = "/aihtml-go/mcp/import_html"
PROTOTYPE_FILE = r"c:\Users\13067\Desktop\AI产品\prototypes\interactive-prototype.html"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": TOKEN,
    "X-Source": "mcp"
}

def import_interactive():
    with open(PROTOTYPE_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()
    
    print(f"文件大小: {len(html_content)} chars")
    print("正在导入交互式原型到墨刀...")
    
    payload = {"htmlString": html_content}
    
    try:
        response = requests.post(
            f"{BASE_URL}{IMPORT_ENDPOINT}",
            headers=HEADERS,
            json=payload,
            timeout=300
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"导入成功！")
            print(f"响应: {json.dumps(result, ensure_ascii=False)[:500]}")
        else:
            print(f"导入失败 - HTTP {response.status_code}: {response.text[:300]}")
    except Exception as e:
        print(f"错误: {e}")

if __name__ == "__main__":
    import_interactive()
