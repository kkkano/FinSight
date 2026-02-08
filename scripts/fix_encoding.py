"""Fix garbled Chinese encoding in frontend source files."""
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fix_chatinput():
    """Fix ChatInput.tsx garbled comments and display text."""
    path = os.path.join(PROJECT_ROOT, "frontend", "src", "components", "ChatInput.tsx")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    changes = 0
    for i, line in enumerate(lines):
        original = line

        # Line 41 (0-indexed): Agent stage mapping comment - already fixed in first edit

        # Line 67: garbled comment about matching agent names
        if "agent" in line and "閸氬秶袨" in line:
            lines[i] = "  // 未匹配时尝试根据 stage 名称匹配 agent\n"
            changes += 1

        # Line 466: Selection Pill comment
        elif "Selection Pill" in line and "閹躲" in line:
            lines[i] = "      {/* Selection Pill - 显示当前选中的内容引用 */}\n"
            changes += 1

        # Lines 472: garbled 'news'/'report' labels
        elif "棣冩應" in line or "棣冩惓" in line:
            lines[i] = "              {activeSelections[0].type === 'news' ? '新闻' : '报告'}{' '}\n"
            changes += 1

        # Line 473: garbled "已选:"
        elif "瀵" in line and "鏁" in line and "activeSelections.length === 1" in line:
            lines[i] = "              已选: {activeSelections.length === 1\n"
            changes += 1

        # Line 475: garbled count text
        elif "閺備即妞" in line or "閹躲儱鎲" in line:
            lines[i] = "                : `${activeSelections.length} 条${activeSelections[0].type === 'news' ? '新闻' : '报告'}`}\n"
            changes += 1

        # Line 480: garbled button title
        elif "閸欐牗绉" in line and "title=" in line:
            lines[i] = '              title="清除选择"\n'
            changes += 1

        if lines[i] != original:
            print(f"  Fixed line {i+1}")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"ChatInput.tsx: {changes} lines fixed")


def fix_client():
    """Fix client.ts garbled Chinese comments."""
    path = os.path.join(PROJECT_ROOT, "frontend", "src", "api", "client.ts")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Map of line patterns -> replacement
    # We'll match by line number and nearby content
    comment_fixes = {
        # line 2: types import note
        "纭繚浣犳湁": "// 确保 types/index.ts 文件定义了这些接口\n",
        # line 3: fallback to any
        "濡傛灉娌℃湁": "// 如果没有，请将 type 导入行注释掉，使用 any 暂时代替\n",
        # line 9: ChatContext description
        "涓存椂涓婁笅鏂": " * Chat Context - 临时上下文（不入库，仅本次请求生效）\n",
        # line 44: timeout
        "120绉掕秴鏃": "  timeout: 120000, // 120秒超时，防止 LLM 生成长文时前端断开\n",
        # line 47: response interceptor
        "鍝嶅簲鎷︽埅鍣": "// 响应拦截器：处理后端返回的非 200 错误\n",
        # line 61: send chat message
        "鍙戦€佽亰澶╂秷鎭": "  // 发送聊天消息（协调者主入口）\n",
        # line 70: compatibility handling
        "鍏煎鎬у鐞": "      // 兼容性处理：如果后端返回结构不一致，确保前端不白屏\n",
        # line 81: fetch kline
        "鑾峰彇 K 绾挎暟鎹": "  // 获取 K 线数据\n",
        # line 94: add chart data
        "灏嗗浘琛ㄦ暟鎹": "  // 将图表数据加入聊天上下文\n",
        # line 103: detect chart type
        "鏅鸿兘妫€娴嬪浘琛ㄧ被": "  // 智能检测图表类型\n",
        # line 112: fallback on detection failure
        "鍗充娇妫€娴嬪け": "      // 即使检测失败也不要阻断流程，返回默认值\n",
        # line 117: get config
        "鑾峰彇鐢ㄦ埛閰嶇疆": "  // 获取用户配置\n",
        # line 124: save config
        "淇濆瓨鐢ㄦ埛閰嶇疆": "  // 保存用户配置\n",
        # line 194: subscription management
        "璁㈤槄绠＄悊": "  // 订阅管理\n",
        # line 222: export PDF
        "瀵煎嚭 PDF": "  // 导出 PDF\n",
        # line 229: responseType blob
        "鍏抽敭锛氬０鏄庤繑鍥炰簩": "      responseType: 'blob' // 关键：声明返回二进制流\n",
        # line 239: health check
        "鍋ュ悍妫€鏌ワ紙鍚瓙": "  // 健康检查（含子Agent状态）\n",
        # line 245: streaming message
        "娴佸紡鍙戦€佹秷鎭": "  // 流式发送消息 - SSE 逐字输出\n",
        # line 251: Phase 2 report data (in function params)
        "鏀寔 report 鏁版嵁": None,  # handle separately
        # line 254: conversation history
        "瀵硅瘽鍘嗗彶": None,  # handle separately
        # line 255: raw SSE callback
        "鍘熷 SSE 浜嬩欢鍥炶皟": None,  # handle separately
        # line 256: temp context
        "涓嶅叆搴擄紝浠呮湰娆¤姹傜敓鏁堬級": None,  # handle separately
        # line 304: send raw event to console
        "鍙戦€佸師濮嬩簨浠跺埌鎺у埗鍙": "            // 发送原始事件到控制台\n",
        # line 319: call onToken immediately
        "绔嬪嵆璋冪敤 onToken": "              // 立即调用 onToken，确保流式效果\n",
        # line 326: extract ThinkingStep
        "浠?thinking 浜嬩欢涓彁鍙": "              // 从 thinking 事件中提取 ThinkingStep 格式的数据\n",
        # line 327: backend sends thinking
        "鍚庣鍙戦€?": "              // 后端发送 {type: \"thinking\", stage: \"...\", message: \"...\", ...}\n",
        # line 336: Phase 2 pass report
        "浼犻€?report": None,  # inline comment, handle separately
        # line 340: Agent progress event
        "Agent 杩涘害浜嬩欢": "            // Agent 进度事件 - 转换为 thinking 格式（兼容后端字段）\n",
        # line 357: parse failure
        "瑙ｆ瀽澶辫触涔熻鍙戦€": "            // 解析失败也要发送到控制台\n",
    }

    # Special: fix title string in exportPDF
    title_fix_old = "FinSight 瀵硅瘽璁板綍"
    title_fix_new = "FinSight 对话记录"

    changes = 0
    for i, line in enumerate(lines):
        # Check for title string fix
        if title_fix_old in line:
            lines[i] = line.replace(title_fix_old, title_fix_new)
            changes += 1
            print(f"  Fixed line {i+1}: title string")
            continue

        # Fix inline comments on parameter lines
        if "鏀寔 report 鏁版嵁" in line:
            lines[i] = line.replace("鏀寔 report 鏁版嵁", "支持 report 数据")
            changes += 1
            print(f"  Fixed line {i+1}: inline comment")
            continue
        if "瀵硅瘽鍘嗗彶" in line:
            lines[i] = line.replace("瀵硅瘽鍘嗗彶", "对话历史")
            changes += 1
            print(f"  Fixed line {i+1}: inline comment")
            continue
        if "鍘熷 SSE 浜嬩欢鍥炶皟" in line:
            lines[i] = line.replace("鍘熷 SSE 浜嬩欢鍥炶皟", "原始 SSE 事件回调")
            changes += 1
            print(f"  Fixed line {i+1}: inline comment")
            continue
        if "涓嶅叆搴擄紝浠呮湰娆¤姹傜敓鏁堬級" in line:
            lines[i] = line.replace("涓嶅叆搴擄紝浠呮湰娆¤姹傜敓鏁堬級", "不入库，仅本次请求生效")
            changes += 1
            print(f"  Fixed line {i+1}: inline comment")
            continue
        if "浼犻€?report" in line:
            # Replace the garbled part of the inline comment
            lines[i] = line.replace("浼犻€?report 鏁版嵁", "传递 report 数据")
            changes += 1
            print(f"  Fixed line {i+1}: inline comment")
            continue

        # Check against comment_fixes
        for pattern, replacement in comment_fixes.items():
            if replacement is None:
                continue
            if pattern in line:
                lines[i] = replacement
                changes += 1
                print(f"  Fixed line {i+1}: {replacement.strip()[:50]}")
                break

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"client.ts: {changes} lines fixed")


if __name__ == "__main__":
    print("=== Fixing ChatInput.tsx ===")
    fix_chatinput()
    print()
    print("=== Fixing client.ts ===")
    fix_client()
    print()
    print("All encoding fixes complete!")
