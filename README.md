# 红楼梦知识库问答系统（本地 TF-IDF 检索 + DeepSeek 生成）

一个纯本地构建索引的中文 RAG 问答系统：把《红楼梦》120 回的 txt 文本切块、用 jieba 分词后训练 TF-IDF 索引，提问时先在本地做向量召回，再把命中的原文片段交给 DeepSeek 生成回答，并在界面上展示引用来源和相似度。

## 功能

- Streamlit 网页问答界面，可调节召回数量与相似度阈值
- 中文分词 + 停用词过滤（本地停用词库 2312 词）
- TF-IDF 索引，特征维度 5000，支持 1-2 gram
- 余弦相似度召回 + 排序取 Top-K
- 回答附带原文片段引用，可溯源
- pickle 双层缓存：文档块缓存 + 向量索引缓存

## 数据规模

| 项目 | 数值 |
| --- | --- |
| 文档数 | 120 个 txt（按回切分） |
| 总字数 | 约 86.9 万字 |
| 文档块数 | 3110（每块不超过 300 字） |
| 特征词维度 | 5000 |
| 停用词 | 2312 |
| 冷启动构建 | 约 4.5 秒 |
| 缓存命中启动 | 约 0.06 秒 |

## 快速开始

```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置密钥
#    .env 里写一行：DEEPSEEK_API_KEY=sk-xxxxxxxx

# 4. 启动网页界面
streamlit run streamlit_app.py

# 或者跑命令行版
python rag_system.py
```

## 项目结构

```
├── rag_system.py        # 核心：文档加载、切块、索引、检索、生成
├── streamlit_app.py     # 网页界面
├── docs/                # 120 回红楼梦 txt
├── 中文停用词库.txt       # 停用词表
├── cache/               # 运行后生成的 pickle 缓存
└── requirements.txt
```

## 实现要点

**切块策略**：先按句末标点（。！？）切句，再累积到 300 字上限成块；单句超长时按 300 字硬切，避免整句被丢弃。

**分词器与缓存的冲突**：`TfidfVectorizer` 保存缓存时会连同 `tokenizer` 一起 pickle。如果传的是绑定方法 `self.chinese_tokenizer`，pickle 会顺带把 `self` 里的 OpenAI 客户端序列化，而它内部持有线程锁，于是报 `TypeError: cannot pickle '_thread.RLock' object`。解决办法是把分词器提到模块级函数，停用词放进模块级集合供它读取。

**pickle 记的是模块名，不是函数本身**：改成模块级函数之后还有一个更隐蔽的坑。pickle 对函数只记录 `模块名.函数名`，用 `python rag_system.py` 直接运行时模块名是 `__main__`，缓存里就写成了 `__main__.chinese_tokenizer`；换 `streamlit run streamlit_app.py` 启动时，`__main__` 变成了 Streamlit 自己的脚本，加载缓存直接报 `AttributeError: module '__main__' has no attribute 'chinese_tokenizer'`。同一份缓存只能被同一种启动方式复用。修法是显式固定 `chinese_tokenizer.__module__ = "rag_system"`，并在脚本直接运行时把 `__main__` 注册成 `rag_system` 的别名。

**参数耦合**：`min_df=2` 与 `max_df=0.95` 在极小语料上会互相矛盾，sklearn 直接抛 `ValueError: max_df corresponds to < documents than min_df`。语料变大后这对参数才成立。

## 说明

- `docs/` 里的文本为公版古籍，仅供学习演示。
- 本项目为个人学习项目，检索层用 TF-IDF 而非向量模型，胜在完全离线、构建快、结果可解释。
