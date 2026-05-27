# @title
"""
对话式多Agent求职助手 v10.0
回到原点：一个真正能和你对话、持续学习的智能助手
"""
import requests
import json
import os
import re
from datetime import datetime, timedelta
from google.colab import userdata
import gradio as gr

# ============================================================
# 配置
# ============================================================
ZHIPU_API_KEY = userdata.get('ZHIPU_API_KEY')
ZHIPU_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
SERPAPI_KEY = userdata.get('SERPAPI_KEY')

BASE_DIR = "/content/agent_users"
CACHE_DIR = "/content/agent_cache"
RULES_FILE = "/content/agent_rules.json"
MAX_HISTORY = 5

for d in [BASE_DIR, CACHE_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# ============================================================
# 大模型调用
# ============================================================
def call_zhipu(messages, temperature=0.7, max_tokens=2000):
    headers = {"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "glm-4-flash", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    try:
        resp = requests.post(ZHIPU_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ API错误：{e}"

# ============================================================
# 缓存
# ============================================================
def get_cached_market(goal, location):
    key = f"{goal}_{location}".replace(" ", "_")
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
        if datetime.now() - datetime.fromisoformat(data["time"]) < timedelta(hours=24):
            return data["report"]
    return None

def set_cached_market(goal, location, report):
    key = f"{goal}_{location}".replace(" ", "_")
    with open(os.path.join(CACHE_DIR, f"{key}.json"), "w") as f:
        json.dump({"time": datetime.now().isoformat(), "report": report}, f)

# ============================================================
# 用户管理
# ============================================================
def list_users():
    if not os.path.exists(BASE_DIR): return []
    return sorted([d for d in os.listdir(BASE_DIR) if os.path.isdir(os.path.join(BASE_DIR, d))])

def load_profile(username):
    path = os.path.join(BASE_DIR, username, "profile.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    return None

def save_profile(username, profile):
    d = os.path.join(BASE_DIR, username)
    if not os.path.exists(d): os.makedirs(d)
    with open(os.path.join(d, "profile.json"), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

def load_history(username):
    path = os.path.join(BASE_DIR, username, "history.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    return []

def save_history(username, history):
    history = history[-MAX_HISTORY:]
    with open(os.path.join(BASE_DIR, username, "history.json"), "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def build_profile_text(profile):
    text = f"姓名：{profile.get('name','')}\n电话：{profile.get('phone','')}\n邮箱：{profile.get('email','')}\n\n"
    edu = profile.get("education", {})
    text += f"教育：{edu.get('school','')}，{edu.get('major','')}，{edu.get('degree','')}，{edu.get('graduation','')}"
    if edu.get("gap"): text += f"\n空档期：{edu['gap']}"
    text += "\n\n工作经历："
    for w in profile.get("work_experience", []):
        text += f"\n- {w['start_date']}至{w['end_date']}：{w['company']}，{w['position']}\n  {w['description']}"
    text += "\n\n项目经历："
    for p in profile.get("projects", []):
        text += f"\n- {p['name']}（{p['type']}）\n  {p['description']}"
    text += "\n\n技能："
    for s in profile.get("skills", []): text += f"\n- {s}"
    text += f"\n\n求职意向：{profile.get('target',{}).get('position','')} | {profile.get('target',{}).get('city','')} | {profile.get('target',{}).get('salary','')}"
    return text

# ============================================================
# 规则管理（持续学习）
# ============================================================
def load_rules():
    if os.path.exists(RULES_FILE):
        with open(RULES_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {"rules": []}

def save_rules(rules):
    with open(RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)

def learn_from_feedback(feedback, goal):
    """从用户反馈中提取规则"""
    rules = load_rules()
    existing = "\n".join([f"- {r}" for r in rules["rules"]]) if rules["rules"] else "无"
    prompt = f"""用户在优化"{goal}"方向的简历时给出了反馈："{feedback}"
已有规则：{existing}
判断反馈是否包含可提炼的普适规则。如果是，输出 ADD_RULE: [规则]。否则输出 NO_RULE。"""
    result = call_zhipu([
        {"role": "system", "content": "你是学习系统，从反馈中提炼普适规则。"},
        {"role": "user", "content": prompt}
    ], temperature=0.3, max_tokens=200)
    if result and result.startswith("ADD_RULE:"):
        new_rule = result.replace("ADD_RULE:", "").strip()
        if new_rule not in rules["rules"]:
            rules["rules"].append(new_rule)
            save_rules(rules)
            return new_rule
    return None

# ============================================================
# 市场分析Agent
# ============================================================
def agent_market(goal, location):
    cached = get_cached_market(goal, location)
    if cached: return cached
    try:
        query = f"{goal} {location} 招聘 site:zhipin.com OR site:51job.com"
        resp = requests.get("https://serpapi.com/search", params={"q": query, "api_key": SERPAPI_KEY, "num": 5, "hl": "zh-cn", "gl": "cn"})
        jobs = "\n".join([f"- {r.get('title')}: {r.get('snippet')}" for r in resp.json().get("organic_results", [])[:5]])
    except:
        jobs = f"基于对'{goal}'岗位的通用市场认知分析。"
    result = call_zhipu([
        {"role": "system", "content": "你是资深职业市场分析师。输出：必备硬技能、加分技能、常见职责、薪资范围、用人方最看重的3个特质、求职者应展示的3个优势。"},
        {"role": "user", "content": f"分析'{goal}'在{location}的需求：\n{jobs}"}
    ], max_tokens=1500)
    if result and "❌" not in result: set_cached_market(goal, location, result)
    return result

# ============================================================
# 简历撰写Agent
# ============================================================
def agent_resume(profile_text, goal, location, market_report="", rules_text=""):
    rules_ctx = f"\n\n【用户长期偏好，必须遵守】：\n{rules_text}" if rules_text else ""
    system = f"""你是专业简历顾问。三级包装策略：
1. 合理深化：把已有内容展开写
2. 合理推断：从经历推断实际具备的技能
3. 适度包装：写"了解XX（自学）"，面试前能突击掌握
红线：不编造不存在的项目或工作经历。自我评价不示弱。
{rules_ctx}"""
    market_ctx = f"\n\n【市场分析】：\n{market_report}" if market_report else ""
    return call_zhipu([
        {"role": "system", "content": system},
        {"role": "user", "content": f"用户背景：\n{profile_text}\n\n目标：{goal} | {location}{market_ctx}\n\n写简历。"}
    ], max_tokens=2000)

# ============================================================
# 面试准备Agent
# ============================================================
def agent_interview(resume, goal, market_report=""):
    system = "你是严苛技术面试官。输出：🔴深度追问（5个+回答要点）🟡弱点预判（3个+防守策略）🟢必问通用题（5个+回答建议）"
    market_ctx = f"\n\n【市场参考】：\n{market_report[:500]}..." if market_report else ""
    return call_zhipu([
        {"role": "system", "content": system},
        {"role": "user", "content": f"目标：{goal}{market_ctx}\n\n简历：\n{resume}\n\n生成面试准备手册。"}
    ], max_tokens=2000)

# ============================================================
# 对话理解：从用户消息中解析意图和参数
# ============================================================
def parse_intent(message, username):
    """让大模型理解用户想做什么"""
    profile = load_profile(username)
    profile_text = build_profile_text(profile) if profile else "无档案"
    
    prompt = f"""你是一个意图解析器。用户正在和求职助手对话。

用户档案：{profile_text}

用户消息："{message}"

请判断用户意图，输出JSON格式：
{{
  "action": "analyze_and_write" | "analyze_only" | "write_only" | "refine_resume" | "chat" | "export" | "switch_goal",
  "goal": "目标岗位（如果有的话）",
  "location": "目标城市（如果有的话）",
  "feedback": "如果是refine_resume，这里是用户的修改意见"
}}

规则：
- 用户说"帮我分析XX岗位"→ action="analyze_only", goal="XX"
- 用户说"帮我写简历"→ action="write_only"（用档案里的求职意向）
- 用户说"帮我分析XX并写简历"→ action="analyze_and_write", goal="XX"
- 用户对简历提修改意见→ action="refine_resume", feedback="用户的修改意见"
- 用户说"导出"或"下载"→ action="export"
- 用户说"我想换成XX岗位"→ action="switch_goal", goal="XX"
- 普通聊天→ action="chat"

只输出JSON，不要其他内容。"""
    
    result = call_zhipu([
        {"role": "system", "content": "你是意图解析器。只输出JSON。"},
        {"role": "user", "content": prompt}
    ], temperature=0.1, max_tokens=300)
    
    try:
        # 尝试提取JSON
        json_match = re.search(r'\{[^}]+\}', result)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    return {"action": "chat", "goal": "", "location": "", "feedback": ""}

# ============================================================
# 对话历史管理
# ============================================================
# 用字典存储每个用户的对话状态
user_states = {}

def get_state(username):
    if username not in user_states:
        user_states[username] = {
            "goal": "",
            "location": "",
            "last_market": "",
            "last_resume": "",
            "last_interview": "",
            "last_md_path": ""
        }
    return user_states[username]

# ============================================================
# 核心对话处理
# ============================================================
def chat_handler(message, history, username, goal_display, location_display):
    """处理用户消息，返回助手回复和更新后的状态"""
    if not username or username == "未选择":
        return history, "❌ 请先在左侧选择或创建用户", goal_display, location_display, None
    
    state = get_state(username)
    intent = parse_intent(message, username)
    action = intent.get("action", "chat")
    
    # 从消息中提取目标
    goal = intent.get("goal", "") or state["goal"]
    location = intent.get("location", "") or state["location"]
    
    reply = ""
    md_path = None
    
    if action == "analyze_and_write" or action == "analyze_only" or (action == "write_only" and goal):
        # 更新状态
        if goal:
            state["goal"] = goal
        if location:
            state["location"] = location
        
        # 获取用户档案
        profile = load_profile(username)
        if not profile:
            reply = "❌ 没有找到你的档案，请先在左侧档案管理区创建。"
        else:
            profile_text = build_profile_text(profile)
            if not state["goal"]:
                state["goal"] = profile.get("target", {}).get("position", "")
            if not state["location"]:
                state["location"] = profile.get("target", {}).get("city", "")
            
            # 市场分析
            reply += f"🔍 正在分析 {state['location']} 的 {state['goal']} 市场...\n\n"
            market = agent_market(state["goal"], state["location"])
            if market and "❌" not in market:
                state["last_market"] = market
                reply += f"📊 **市场分析完成**\n\n"
            else:
                reply += "❌ 市场分析失败\n"
                return history, reply, goal_display, location_display, None
            
            if action == "analyze_only":
                reply += market
            else:
                # 写简历
                rules = load_rules()
                rules_text = "\n".join([f"- {r}" for r in rules["rules"]]) if rules["rules"] else ""
                reply += "✍️ 正在基于市场分析和你的背景写简历...\n\n"
                resume = agent_resume(profile_text, state["goal"], state["location"], market, rules_text)
                if resume and "❌" not in resume:
                    state["last_resume"] = resume
                    reply += f"📄 **简历**\n\n{resume}\n\n"
                    
                    # 面试准备
                    reply += "🎤 正在准备面试问答...\n\n"
                    interview = agent_interview(resume, state["goal"], market)
                    if interview and "❌" not in interview:
                        state["last_interview"] = interview
                        reply += f"🎤 **面试准备**\n\n{interview}\n\n"
                        
                        # 保存
                        history_data = load_history(username)
                        history_data.append({
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "goal": state["goal"], "location": state["location"],
                            "market": market, "resume": resume, "interview": interview
                        })
                        save_history(username, history_data)
                        
                        # 生成MD
                        md = f"# 求职协作报告\n**用户**：{username} | **目标**：{state['goal']} | **时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n## 📊 市场分析\n{market}\n\n## 📄 简历\n{resume}\n\n## 🎤 面试准备\n{interview}\n"
                        state["last_md_path"] = os.path.join(BASE_DIR, username, f"{state['goal']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
                        with open(state["last_md_path"], "w", encoding="utf-8") as f: f.write(md)
                        md_path = state["last_md_path"]
                        
                        reply += "✅ 全部完成！你可以：\n- 对简历提修改意见（如'技能部分再强化一下'）\n- 说'导出'下载报告\n- 说'换成XX岗位'切换方向"
                    else:
                        reply += "❌ 面试准备失败"
                else:
                    reply += "❌ 简历生成失败"
    
    elif action == "refine_resume":
        feedback = intent.get("feedback", message)
        if state["last_resume"]:
            profile = load_profile(username)
            profile_text = build_profile_text(profile) if profile else ""
            rules = load_rules()
            rules_text = "\n".join([f"- {r}" for r in rules["rules"]]) if rules["rules"] else ""
            
            reply += f"🔧 根据你的意见修改简历...\n\n"
            resume = agent_resume(profile_text, state["goal"], state["location"], state["last_market"], rules_text)
            if resume and "❌" not in resume:
                state["last_resume"] = resume
                reply += f"📄 **修改后的简历**\n\n{resume}\n\n"
                reply += "还有其他要改的吗？"
            else:
                reply += "❌ 修改失败，请重试"
            
            # 学习规则
            learned = learn_from_feedback(feedback, state["goal"])
            if learned:
                reply += f"\n\n🧠 我学到了：{learned}"
        else:
            reply += "还没有生成简历，请先说'帮我写简历'或'帮我分析XX岗位并写简历'。"
    
    elif action == "export":
        if state["last_md_path"] and os.path.exists(state["last_md_path"]):
            md_path = state["last_md_path"]
            reply = "📥 报告已准备好，请点击下载。"
        else:
            reply = "还没有生成报告，请先说'帮我分析XX岗位并写简历'。"
    
    elif action == "switch_goal":
        if goal:
            state["goal"] = goal
            reply = f"✅ 已切换到 {goal}。你想让我分析这个岗位并写简历吗？"
        else:
            reply = "请告诉我你想换成什么岗位，比如'换成AI产品经理'。"
    
    else:
        # 普通对话
        profile = load_profile(username)
        profile_text = build_profile_text(profile) if profile else "无档案"
        rules = load_rules()
        rules_text = "\n".join([f"- {r}" for r in rules["rules"]]) if rules["rules"] else ""
        
        reply = call_zhipu([
            {"role": "system", "content": f"你是求职助手。用户档案：{profile_text}\n用户偏好规则：{rules_text}\n\n你可以帮用户：分析岗位市场、写简历、准备面试、修改简历。用户说'帮我分析XX'或'帮我写简历'时，你会自动调度多个Agent协作。请友好、简洁地回复。"},
            {"role": "user", "content": message}
        ], max_tokens=500)
    
    # 更新显示
    goal_display = state["goal"] or goal_display
    location_display = state["location"] or location_display
    
    # 追加到聊天历史
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    
    return history, "", goal_display, location_display, md_path

# ============================================================
# 用户管理界面逻辑
# ============================================================
def on_profile_select(username):
    if not username or username == "+ 新建用户":
        return "", "", "", "", "", "", "", "", "", "", "", "", "", "请创建新用户"
    profile = load_profile(username)
    if not profile:
        return "", "", "", "", "", "", "", "", "", "", "", "", "", "档案加载失败"
    edu = profile.get("education", {})
    work = profile.get("work_experience", [])
    proj = profile.get("projects", [])
    skills = profile.get("skills", [])
    target = profile.get("target", {})
    work_text = "\n".join([f"{w['company']},{w['position']},{w['start_date']}-{w['end_date']},{w['description']}" for w in work])
    proj_text = "\n".join([f"{p['name']},{p['type']},{p['description']}" for p in proj])
    skills_text = "\n".join(skills)
    return (profile.get("name",""), profile.get("phone",""), profile.get("email",""),
            edu.get("school",""), edu.get("major",""), edu.get("degree",""), edu.get("graduation",""), edu.get("gap",""),
            work_text, proj_text, skills_text,
            target.get("position",""), target.get("city",""), target.get("salary",""),
            f"已加载 {username}")

def save_user_profile(username, name, phone, email, school, major, degree, graduation, gap, work_text, proj_text, skills_text, target_pos, target_city, target_salary):
    if not username or username == "+ 新建用户":
        username = name.strip().lower().replace(" ", "_") or f"user_{datetime.now().strftime('%H%M%S')}"
    if not username:
        return "❌ 请输入姓名"
    profile = {
        "name": name, "phone": phone, "email": email,
        "education": {"school": school, "major": major, "degree": degree, "graduation": graduation, "gap": gap},
        "work_experience": [], "projects": [], "skills": [],
        "target": {"position": target_pos, "city": target_city, "salary": target_salary}
    }
    for line in work_text.strip().split("\n"):
        if line.strip() and "," in line:
            parts = line.split(",")
            if len(parts) >= 4:
                profile["work_experience"].append({"company": parts[0].strip(), "position": parts[1].strip(), "start_date": parts[2].strip(), "end_date": parts[3].strip(), "description": ",".join(parts[4:]).strip()})
    for line in proj_text.strip().split("\n"):
        if line.strip() and "," in line:
            parts = line.split(",")
            if len(parts) >= 3:
                profile["projects"].append({"name": parts[0].strip(), "type": parts[1].strip(), "description": ",".join(parts[2:]).strip()})
    for line in skills_text.strip().split("\n"):
        if line.strip(): profile["skills"].append(line.strip())
    save_profile(username, profile)
    return f"✅ {username}（{name}）已保存"

# ============================================================
# 界面
# ============================================================
def create_ui():
    with gr.Blocks(title="求职助手 v10.0") as app:
        gr.Markdown("# 🤖 对话式求职助手 v10.0")
        gr.Markdown("和我聊天，我会帮你分析岗位、写简历、准备面试。试试说：**帮我分析东莞的AI产品经理岗位并写简历**")
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 👤 用户")
                chat_user = gr.Dropdown(label="当前用户", choices=list_users() + ["+ 新建用户"], value=list_users()[0] if list_users() else "+ 新建用户", interactive=True)
                refresh_btn = gr.Button("🔄刷新", size="sm")
                goal_display = gr.Textbox(label="当前求职方向", value="未设置", interactive=False)
                location_display = gr.Textbox(label="当前城市", value="未设置", interactive=False)
                
                gr.Markdown("### 💡 试试这样说")
                gr.Markdown("- 帮我分析东莞的AI产品经理并写简历\n- 技能部分再强化一下\n- 换成外卖运营岗位\n- 导出")
                
                download_out = gr.File(label="📥 下载最新报告", visible=True)
            
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(label="对话", type="messages", height=500)
                msg_input = gr.Textbox(label="", placeholder="输入你的需求...", scale=4)
                send_btn = gr.Button("发送", variant="primary")
        
        with gr.Accordion("📋 档案管理", open=False):
            with gr.Row():
                profile_user = gr.Dropdown(label="编辑用户", choices=list_users() + ["+ 新建用户"], interactive=True)
                profile_refresh = gr.Button("🔄刷新", size="sm")
            with gr.Row():
                name = gr.Textbox(label="姓名")
                phone = gr.Textbox(label="电话")
                email = gr.Textbox(label="邮箱")
            with gr.Row():
                school = gr.Textbox(label="学校")
                major = gr.Textbox(label="专业")
                degree = gr.Textbox(label="学历")
                graduation = gr.Textbox(label="毕业时间")
            gap = gr.Textbox(label="空档期")
            gr.Markdown("### 工作经历（每行：公司,职位,时间,描述）")
            work_input = gr.Textbox(label="", lines=3, placeholder="湘禾印象,外卖运营,2026.1-至今,管理25家连锁外卖平台")
            gr.Markdown("### 项目经历（每行：名称,类型,描述）")
            proj_input = gr.Textbox(label="", lines=3, placeholder="图书管理系统,课程设计,Java+MySQL实现")
            gr.Markdown("### 技能（每行一条）")
            skills_input = gr.Textbox(label="", lines=3, placeholder="Python\nSQL\nGit")
            with gr.Row():
                target_pos = gr.Textbox(label="目标岗位")
                target_city = gr.Textbox(label="目标城市")
                target_salary = gr.Textbox(label="期望薪资")
            save_btn = gr.Button("💾 保存档案", variant="secondary")
            profile_msg = gr.Textbox(label="操作结果", interactive=False)
        
        # 状态
        chat_state = gr.State([])
        
        # 事件
        refresh_btn.click(lambda: gr.Dropdown(choices=list_users() + ["+ 新建用户"]), outputs=chat_user)
        profile_refresh.click(lambda: gr.Dropdown(choices=list_users() + ["+ 新建用户"]), outputs=profile_user)
        
        profile_user.change(on_profile_select, profile_user,
            [name, phone, email, school, major, degree, graduation, gap, work_input, proj_input, skills_input, target_pos, target_city, target_salary, profile_msg])
        
        save_btn.click(save_user_profile,
            [profile_user, name, phone, email, school, major, degree, graduation, gap, work_input, proj_input, skills_input, target_pos, target_city, target_salary],
            profile_msg)
        
        def on_send(message, history, username, goal_disp, loc_disp):
            if not message.strip():
                return history, "", goal_disp, loc_disp, None
            new_history, _, new_goal, new_loc, md_path = chat_handler(message, history, username, goal_disp, loc_disp)
            return new_history, "", new_goal, new_loc, md_path
        
        send_btn.click(on_send, [msg_input, chat_state, chat_user, goal_display, location_display],
                       [chatbot, msg_input, goal_display, location_display, download_out])
        msg_input.submit(on_send, [msg_input, chat_state, chat_user, goal_display, location_display],
                         [chatbot, msg_input, goal_display, location_display, download_out])
    
    return app

if __name__ == "__main__":
    app = create_ui()
    app.launch(share=True)
  