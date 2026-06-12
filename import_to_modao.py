import os
import json
import requests
import time

TOKEN = "a766805314bc8234cdee771ac14421f6"
BASE_URL = "https://modao.cc"
IMPORT_ENDPOINT = "/aihtml-go/mcp/import_html"
PROTOTYPES_DIR = r"c:\Users\13067\Desktop\AI产品\prototypes"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": TOKEN,
    "X-Source": "mcp"
}

# 按顺序导入的文件列表
FILES = [
    ("01-homepage.html", "首页"),
    ("02-humanities.html", "人文社科"),
    ("02-engineering.html", "工科"),
    ("02-science.html", "理科"),
    ("03-readiness-selection.html", "思路选择"),
    ("04-researcher-chat.html", "研究员对话"),
    ("05-reviewer-chat.html", "审查员对话"),
    ("06-architect-chat.html", "架构师对话"),
    ("07-custom-agent.html", "自定义Agent"),
    ("08-settings.html", "设置"),
]

def import_html(filename, page_name):
    filepath = os.path.join(PROTOTYPES_DIR, filename)
    if not os.path.exists(filepath):
        print(f"[SKIP] {filename} not found")
        return False
    
    with open(filepath, "r", encoding="utf-8") as f:
        html_content = f.read()
    
    print(f"[IMPORT] {page_name} ({filename}) - {len(html_content)} chars...")
    
    payload = {
        "htmlString": html_content
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}{IMPORT_ENDPOINT}",
            headers=HEADERS,
            json=payload,
            timeout=300
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"[OK] {page_name} imported successfully!")
            if result.get("message"):
                print(f"  Message: {result['message']}")
            if result.get("data"):
                print(f"  Data: {json.dumps(result['data'], ensure_ascii=False)[:200]}")
            return True
        else:
            print(f"[ERROR] {page_name} - HTTP {response.status_code}: {response.text[:300]}")
            return False
    except Exception as e:
        print(f"[ERROR] {page_name} - {str(e)}")
        return False

def main():
    print("=" * 60)
    print("墨刀原型批量导入工具")
    print(f"API: {BASE_URL}{IMPORT_ENDPOINT}")
    print(f"文件数: {len(FILES)}")
    print("=" * 60)
    
    success_count = 0
    fail_count = 0
    
    for filename, page_name in FILES:
        result = import_html(filename, page_name)
        if result:
            success_count += 1
        else:
            fail_count += 1
        # 避免请求过快
        time.sleep(2)
    
    print("\n" + "=" * 60)
    print(f"导入完成！成功: {success_count}, 失败: {fail_count}")
    print("=" * 60)

if __name__ == "__main__":
    main()
