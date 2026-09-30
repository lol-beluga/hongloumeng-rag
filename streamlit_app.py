import streamlit as st
from pathlib import Path
from rag_system import RagSystem
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700&display=swap');

.main-header {
    font-size: 3rem;
    background: linear-gradient(135deg, #8B4513, #CD853F);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-align: center;
    margin-bottom: 2rem;
    font-weight: 700;
    font-family: 'Noto Serif SC', serif;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
}

.subtitle {
    text-align: center;
    color: #666;
    font-style: italic;
    margin-bottom: 2rem;
    font-family: 'Noto Serif SC', serif;
}

.chat-message {
    padding: 1.2rem;
    border-radius: 1rem;
    margin-bottom: 1rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    transition: all 0.3s ease;
    animation: fadeIn 0.5s ease-in;
}

.chat-message:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.user-message {
    background: linear-gradient(135deg, #e3f2fd, #bbdefb);
    border-left: 4px solid #2196f3;
    margin-left: 2rem;
}

.assistant-message {
    background: linear-gradient(135deg, #fff8e1, #ffecb3);
    border-left: 4px solid #8B4513;
    margin-right: 2rem;
}

.source-info {
    background: linear-gradient(135deg, #f3e5f5, #e1bee7);
    padding: 0.8rem;
    border-radius: 0.8rem;
    margin-top: 0.8rem;
    font-size: 0.9rem;
    border: 1px solid #ce93d8;
    transition: all 0.3s ease;
}

.source-info:hover {
    background: linear-gradient(135deg, #e8eaf6, #c5cae9);
    border-color: #9c27b0;
}

.status-success {
    color: #2e7d32;
    font-weight: bold;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
}

.status-error {
    color: #d32f2f;
    font-weight: bold;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
}

.status-warning {
    color: #f57c00;
    font-weight: bold;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
}

.example-button {
    background: linear-gradient(135deg, #fff3e0, #ffe0b2);
    border: 1px solid #ffb74d;
    border-radius: 0.5rem;
    padding: 0.5rem;
    margin: 0.2rem 0;
    transition: all 0.3s ease;
    cursor: pointer;
}

.example-button:hover {
    background: linear-gradient(135deg, #ffe0b2, #ffcc80);
    transform: translateX(5px);
}

.sidebar-section {
    background: linear-gradient(135deg, #fafafa, #f5f5f5);
    padding: 1rem;
    border-radius: 0.8rem;
    margin-bottom: 1rem;
    border: 1px solid #e0e0e0;
}

.typing-indicator {
    display: inline-block;
    animation: typing 1.5s infinite;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes typing {
    0%, 60%, 100% { opacity: 1; }
    30% { opacity: 0.5; }
}

.metric-card {
    background: linear-gradient(135deg, #e8f5e8, #c8e6c9);
    padding: 1rem;
    border-radius: 0.8rem;
    text-align: center;
    margin: 0.5rem 0;
    border: 1px solid #81c784;
}

.progress-bar {
    background: linear-gradient(90deg, #4caf50, #8bc34a);
    height: 4px;
    border-radius: 2px;
    animation: progress 2s ease-in-out;
}

@keyframes progress {
    from { width: 0%; }
    to { width: 100%; }
}
</style>
""", unsafe_allow_html=True)


def display_chat_message(role, content, sources=None, typing=False):
    """显示聊天消息"""
    if role == "user":
        st.markdown(f"""
        <div class="chat-message user-message">
            <strong>🙋‍♀️ 您:</strong> {content}
        </div>
        """, unsafe_allow_html=True)
    else:
        typing_indicator = '<span class="typing-indicator">💭</span>' if typing else '🤖'
        st.markdown(f"""
        <div class="chat-message assistant-message">
            <strong>{typing_indicator} 红楼梦助手:</strong> {content}
        </div>
        """, unsafe_allow_html=True)

        if sources:
            with st.expander(f"📖 参考文档片段 ({len(sources)}个)", expanded=False):
                for i, source in enumerate(sources, 1):
                    similarity_color = "#4caf50" if source['similarity'] > 0.5 else "#ff9800" if source[
                                                                                                     'similarity'] > 0.3 else "#f44336"
                    st.markdown(f"""
                    <div class="source-info">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <strong>📄 片段 {i}: {source['source']}</strong>
                            <span style="background: {similarity_color}; color: white; padding: 0.2rem 0.5rem; border-radius: 1rem; font-size: 0.8rem;">
                                相似度: {source['similarity']:.3f}
                            </span>
                        </div>
                        <div style="background: rgba(255,255,255,0.8); padding: 0.5rem; border-radius: 0.5rem; border-left: 3px solid {similarity_color};">
                            <em>📝 内容预览:</em><br>
                            {source['content_preview']}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)


def getEnvInfo(key):
    env_file = Path(".env")

    env_lines = []
    env_res = None
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            env_lines = f.readlines()

    # 查找对应的配置项
    for i, line in enumerate(env_lines):
        if line.strip().startswith(f"{key}="):
            env_res = line.strip().split("=")[1]

    return env_res

def init_session_state():
    # 系统状态
    if 'system_init' not in st.session_state:
        st.session_state.system_init = False
    # deepseek_key
    if 'api_key' not in st.session_state:
        st.session_state.api_key = getEnvInfo('DEEPSEEK_API_KEY')
    # 快捷问题
    if 'preset_question' not in st.session_state:
        st.session_state.preset_question = ""
    # 选择角色
    if 'selected_role' not in st.session_state:
        st.session_state.selected_role = ""

    # 自动初始化项目
    if not st.session_state.system_init:
        rag = RagSystem(st.session_state.api_key)
        rag.initialize()
        st.session_state.rag_system = rag
        st.session_state.system_init = True

def check_cache_exists():
    cache_dir = Path("cache")
    vectors_cache = cache_dir / "doc_vectors.pkl"
    chunks_cache = cache_dir / "doc_chunks.pkl"
    return vectors_cache.exists() and chunks_cache.exists()

def main():
    # st.header("📚图书智能检索系统")
    st.markdown('<h1 class="main-header">📚图书智能检索系统</h1>', unsafe_allow_html=True)
    init_session_state()

    # 侧边栏
    with st.sidebar:
        st.header("⚙️系统配置")
        api_key_input = st.text_input(
            "🔑DeepSeek API密钥",
            value=st.session_state.api_key,
            help="请输入您的DeepSeek API密钥。如已保存到配置文件，刷新页面后会自动加载。",
            placeholder="sk-xxxxxxxxxxxxxxxxxxxx",
            type="password"
        )

        if api_key_input:
            st.session_state.api_key = api_key_input
        else:
            st.session_state.system_init = False

        st.header("📊系统状态")
        if not st.session_state.system_init:
            st.markdown('<p class="status-warning">⚠️系统未初始化</p>', unsafe_allow_html=True)
        else:
            st.markdown('<p class="status-success">✅系统已就绪</p>', unsafe_allow_html=True)
            if st.session_state.rag_system:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"""
                        <div class="metric-card">
                            <h3>📄</h3>
                            <p>{len(st.session_state.rag_system.documents)}</p>
                            <small>文档数量</small>
                        </div>
                    """, unsafe_allow_html=True)
                with col2:
                    st.markdown(f"""
                        <div class="metric-card">
                            <h3>📦</h3>
                            <p>{len(st.session_state.rag_system.doc_chunks)}</p>
                            <small>文档块</small>
                        </div>
                    """, unsafe_allow_html=True)

        # 获取按钮状态
        cache_exists = check_cache_exists()
        if cache_exists and st.session_state.system_init:
            st.button("🔄 重新初始化系统", use_container_width=True)
        else:
            if st.button("🚀 加载缓存数据", use_container_width=True):
                init_session_state()

        # 搜索参数配置
        if st.session_state.system_init:
            st.header('🔍 搜索参数')
            # 最大返回文档数量
            top_k = st.slider(
                '📄 最大返回文档数量',
                min_value=1,
                max_value=20,
                value=10,
                help='设置搜索时最多返回多少个相关文档片段'
            )

            # 相似度阈值
            similarity_threshold = st.slider(
                '📊 相似度阈值',
                min_value=0.0,
                max_value=1.0,
                value=0.01,
                step=0.01,
                help='只返回相似度高于此值的文档片段，值越高结果越精确'
            )

            # 保存到session_state
            st.session_state.search_top_k = top_k
            st.session_state.search_similarity_threshold = similarity_threshold

    # 主要对话区域
    st.header("💬 与AI智能助手对话")

    # 快捷问题
    st.subheader("⚡ 快捷问题")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("👥 人物关系", use_container_width=True):
            if st.session_state.system_init:
                # 设置预选问题到session_state
                st.session_state.preset_question = '红楼梦中主要人物之间的关系是怎样的？'
                st.session_state.selected_role = '人物关系'
    with col2:
        if st.button("📖 情节梗概", use_container_width=True):
            if st.session_state.system_init:
                # 设置预选问题到session_state
                st.session_state.preset_question = '请简述红楼梦第一回的主要情节。'
                st.session_state.selected_role = '情节梗概'
    with col3:
        if st.button("🎨 文学手法", use_container_width=True):
            if st.session_state.system_init:
                # 设置预选问题到session_state
                st.session_state.preset_question = '红楼梦运用了哪些文学表现手法？'
                st.session_state.selected_role = '文学手法'
    with col4:
        if st.button("💎 象征意义", use_container_width=True):
            if st.session_state.system_init:
                # 设置预选问题到session_state
                st.session_state.preset_question = '通灵宝玉有什么象征意义？'
                st.session_state.selected_role = '象征意义'

    # 显示已选择的角色
    if st.session_state.selected_role:
        st.info(f"✅ 已选择角色: {st.session_state.selected_role}")

    # 用户输入区域
    with st.form(key="char_form", clear_on_submit=True):
        col1, col2 = st.columns([5, 1])
        with col1:
            user_input = st.text_area(
                '💬 请输入您的问题',
                value=st.session_state.preset_question,
                placeholder="甄士隐是谁？他在故事中起到什么作用？\n\n💡 提示：您可以询问人物、情节、诗词、象征意义等任何关于红楼梦的问题",
                height=100,
                label_visibility="visible",
            )
        with col2:
            st.markdown("<br/>", unsafe_allow_html=True)
            submit_button = st.form_submit_button("🚀 发送", use_container_width=True, type="primary")
            clear_button = st.form_submit_button("🧹 清空", use_container_width=True)

    # 处理情况
    if clear_button:
        st.session_state.preset_question = ''
        st.session_state.selected_role = ''

    # 处理发送
    if submit_button and user_input.strip():
        # 如果系统是初始化完成
        if st.session_state.system_init and st.session_state.rag_system:
            # 先清空预设问题和选择的角色
            st.session_state.preset_question = ''
            st.session_state.selected_role = ''

            # 显示对话效果
            display_chat_message(role="user", content=user_input)

            # 显示思考中的状态
            thinking_placeholder = st.empty()
            with thinking_placeholder:
                display_chat_message(role="assistant", content="正在思考中，请稍后...", typing=True)

            with st.spinner("🔍 正在搜索相关文档... 📄 正在生成回答..."):
                # 获取搜索参数
                top_k = getattr(st.session_state, 'search_top_k', 10)
                similarity_threshold = getattr(st.session_state, 'search_similarity_threshold', 0.01)
                result = st.session_state.rag_system.ask(user_input, top_k=top_k, similarity_threshold=similarity_threshold)

            # 清除思考的状态
            thinking_placeholder.empty()

            # 处理模型返回的数据
            processed_sources = []
            for source in result['sources']:
                if 'content_preview' in source:
                    content = source['content_preview']
                elif 'content' in source:
                    content = source['content'][:200] + '...' if len(source['content']) > 200 else source['content']
                else:
                    content = '无内容预览'

                processed_sources.append({
                    'source': source['source'],
                    'similarity': source['similarity'],
                    'content_preview': content,
                })

            # 显示助手回答
            display_chat_message(role="assistant", content=result['answer'], sources=processed_sources)

if __name__ == "__main__":
    main()