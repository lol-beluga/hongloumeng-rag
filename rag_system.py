import os
import re
import sys
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
import jieba
import pickle
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from openai import OpenAI

# 模块级停用词集合：分词器要放到模块级才能被 pickle，它必须引用模块级变量
STOPWORDS = set()


def chinese_tokenizer(text):
    """中文分词器。
    放在模块级而不是类方法里，是因为 TfidfVectorizer 会把分词器一起 pickle 进缓存；
    绑定方法会连带把 self（里面有 OpenAI 客户端的线程锁）一起序列化，直接报错。
    """
    words = list(jieba.cut(text))
    punctuation = "，。！？；：“”（）【】《》"
    filtered_words = []
    for word in words:
        word = word.strip()
        if (
            word and
            len(word) > 1 and  # 过滤单字符
            word not in STOPWORDS and  # 停用词过滤
            not all(char in punctuation for char in word)):  # 标点过滤
            filtered_words.append(word)
    return filtered_words


# pickle 记录函数的方式是"模块名.函数名"。直接 python rag_system.py 运行时模块名是 __main__，
# 缓存会被写成 __main__.chinese_tokenizer，换 streamlit 启动就找不到，所以把模块名钉死成 rag_system
chinese_tokenizer.__module__ = "rag_system"
if __name__ == "__main__":
    sys.modules.setdefault("rag_system", sys.modules["__main__"])


def load_api_key() -> str:
    """从环境变量或 .env 读取 DeepSeek 密钥，避免把密钥写进代码提交到网上"""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip()
    raise RuntimeError("未找到 DEEPSEEK_API_KEY，请在 .env 中配置或设置环境变量")


class RagSystem:
    def __init__(self,api_key:str,docs_dir:str="docs"):
        self.api_key = api_key
        #DeepSeek 兼容 OpenAI 协议，用 openai SDK 直连
        self.docs_dir = Path(docs_dir)
        self.client = OpenAI(
            base_url="https://api.deepseek.com",
            api_key=api_key,
        )
        #文档存储
        self.documents = []
        self.doc_chunks = []
        self.vectorizer = None
        self.vector_index = None#向量矩阵也挂到self上，后面检索要用
        self.doc_vectors = None
        #加载停用词库（分词器已移到模块级，它读取 STOPWORDS）
        STOPWORDS.update(self.load_stopwords())
        #缓存文件
        self.cache_dir = Path("cache")
        self.cache_dir.mkdir(exist_ok=True)
        self.chunks_cache_dir = self.cache_dir / "doc_chunks.pkl"
        self.vectors_cache = self.cache_dir / "doc_vectors.pkl"

    def load_stopwords(self):
        """加载中文停用词库"""
        stopwords_file = Path("中文停用词库.txt")
        stopwords = set()
        if stopwords_file.exists():#exists是方法，必须加括号；不加括号它是个方法对象，永远为真
            try:
                with open(stopwords_file, "r", encoding="utf-8") as f:#变量名是stopwords_file，别写成stop_words_file
                    for line in f:
                        word = line.strip()
                        if word:
                            stopwords.add(word)
                print(f"已加载{len(stopwords)}个停用词")#统计挪到循环外面，否则每读一行就打印一次
            except Exception as e:
                print(f"加载停用词库时出错：{e}")
        else:
            print("未找到停用词库文件，将使用默认的停用词")
            stopwords.update(['的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'])
        return stopwords

    def initialize(self):
        print("智能图书系统初始化")
        self.load_documents()
        self.preprocess_documents()
        self.build_vector_index()


    def load_documents(self):
        """加载文档"""
        print("正在加载红楼梦文档")
        for file_path in self.docs_dir.glob("*.txt"):
            #print(file_path)#调试用：每个文件路径都打印，嫌吵就注释掉
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                #print(content)#调试用：会把整本小说全文打印出来，强烈建议保持注释
                if content:
                    self.documents.append({
                        "filename":file_path.name,
                        "content":content,
                        "path":str(file_path),
                    })

            except Exception as e:
             print(f"加载文件{file_path}时出错:{e}")
        print(f"共加载了{len(self.documents)}个文档")#挪到for循环外面，只打印一次

    def split_text_chunks(self,text:str,chunk_size:int=300):
        """将文本分割成块（保证每一块长度<=chunk_size）"""
        #按句末标点切分，标点保留在句尾（原写法没有字符类，实际一句都切不开）
        sentences= re.split(r"(?<=[。！？!?])",text)
        sentences= [s.strip() for s in sentences if s.strip()]
        chunks = []
        current_chunk = ""

        for sentence in sentences:
            while len(sentence)>chunk_size:#单句本身就超长时，按chunk_size硬切
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                chunks.append(sentence[:chunk_size])
                sentence = sentence[chunk_size:]
            if not current_chunk:
                current_chunk = sentence
            elif len(current_chunk)+len(sentence)<=chunk_size:  #句子长度动态调整块的大小
                current_chunk += sentence
            else:
                chunks.append(current_chunk)
                current_chunk = sentence
        if current_chunk:
            chunks.append(current_chunk.strip())
        return chunks


    def preprocess_documents(self):
        """预处理文档，分割文档"""
        #检查缓存：只要cache/doc_chunks.pkl存在就直接读，跳过切分
        if self.chunks_cache_dir.exists():
            print("发现文档块缓存，正在加载")
            with open(self.chunks_cache_dir, "rb") as f:
                self.doc_chunks = pickle.load(f)
            print(f"从缓存加载了{len(self.doc_chunks)}个文档块")
            return

        for doc in self.documents:
            chunks = self.split_text_chunks(doc["content"])
            for i,chunk in enumerate(chunks):
                self.doc_chunks.append({
                    "content":chunk,
                    'source':doc['filename'],
                    "chunk_id":i,
                    "full_path":doc['path']
                })
        #print(self.doc_chunks)#调试用：会把3110个字典全部打印出来，嫌吵就注释掉
        print(f"文档预处理完成，共生成 {len(self.doc_chunks)} 个文档块")
        #保存缓存：必须写在切分完成之后。原来这段写在load_stopwords的return下面，永远执行不到
        with open(self.chunks_cache_dir, "wb") as f:
            pickle.dump(self.doc_chunks, f)
        print(f"文档块缓存已保存到 {self.chunks_cache_dir}")
    def build_vector_index(self):
        """
    TF-IDF = 词频(TF) × 逆文档频率(IDF)
	TF = 某个词在文章中的出现次数 / 文章的总词数
	IDF = log(语料库的文档总数 / (包含该词的文档数 + 1))
        """
        #检查向量缓存：有cache/doc_vectors.pkl就不再重新训练，直接返回，什么都不打印（除了下面两行提示）
        if self.vectors_cache.exists():
            print("发现向量缓存，正在加载")
            with open(self.vectors_cache, "rb") as f:
                self.vectorizer, self.vector_index = pickle.load(f)
            print(f"从缓存加载了向量索引：{self.vector_index.shape[0]}个文档块，{self.vector_index.shape[1]}个特征词")
            print("向量索引加载完成")
            return

        """构建向量索引"""
        print("正在构建向量索引")
        tv = TfidfVectorizer(
            tokenizer=chinese_tokenizer,#关键：指定模块级分词器，这样缓存才能被 pickle
            token_pattern=None,#指定tokenizer后加上这句，sklearn就不会再发那条警告
            max_features=5000,#能够取到的最大特征
            min_df=2,#忽略出现少于两次的词
            max_df=0.95,#忽略出现概率大于95%以上的词
            ngram_range=(1,2),#包含1-2个词的词组
        )
        self.vectorizer = tv#关键：把建好的向量化器保存到self上，否则之前是None，jieba根本不会被调用
        #特征的判断
        #1.评论 短句
        #2.新闻文章 产品描述
        #3.学术论文 技术文档 文学作品
        text = [chunk["content"] for chunk in self.doc_chunks]
        self.vector_index = self.vectorizer.fit_transform(text)#这里才真正逐个块调用chinese_tokenizer分词
        print(f"向量索引构建完成，共{self.vector_index.shape[0]}个文本块，{self.vector_index.shape[1]}个特征词")
        #保存向量缓存：向量化器和稀疏矩阵一起存，下次可以直接transform查询
        with open(self.vectors_cache, "wb") as f:
            pickle.dump((self.vectorizer, self.vector_index), f)
        print(f"向量索引缓存已保存到 {self.vectors_cache}")

    def search_chunks(self,query:str,top_k:int = 10,similarity_threshold:float=0.01):
        if self.vectors_cache.exists():
            if self.vectorizer is None or self.vector_index is None:
                raise ValueError("向量索引未构建，请先调用build_vector_index()")

        #向量化查询
        query_vector = self.vectorizer.transform([query])

        #计算（余弦）相似度 [0,1]
        similarities = cosine_similarity(query_vector, self.vector_index).flatten()
        # arr = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
        # print(np.where(arr > 5))
        valid_index = np.where(similarities > similarity_threshold)[0]
        #按照相似度从大到小排列
        sorted_index = valid_index[np.argsort(similarities[valid_index])[::-1]]
        top10_index = sorted_index[:top_k]
        results = []#本地列表；第6行那句 jieba 自动导入是 IDE 误补全，已删
        for idx in top10_index:
            chunk = self.doc_chunks[idx].copy()
            chunk["similarity"] = float(similarities[idx])
            results.append(chunk)
        return results

    def generate_answer(self,query:str,context_chunks):
        #构建上下文
        context = "\n\n".join([f"文档片段{i + 1}: {chunk['content']}" for i, chunk in enumerate(context_chunks)])
        #系统提示词：给模型定角色，并把检索到的文档片段塞进去
        system_prompt = """
# Role: 红楼梦研究专家

## Profile
- language: 中文
- description: 精通《红楼梦》文本及红学研究，能够深入解析作品的人物、情节、诗词及文化内涵
- background: 多年从事《红楼梦》研究与教学，参与过多项红学课题研究
- personality: 严谨细致，富有文人气质，善于引经据典
- expertise: 文本分析、人物研究、诗词鉴赏、文化解读
- target_audience: 红学爱好者、文学研究者、学生群体

## Skills

1. 文本解析能力
   - 情节梳理: 能准确还原小说情节脉络
   - 细节把握: 对文本细节有敏锐洞察力
   - 人物分析: 深入剖析人物性格与命运
   - 诗词解读: 精准解析书中诗词内涵

2. 学术研究能力
   - 文献考证: 熟悉各类红学研究成果
   - 文化阐释: 揭示作品背后的文化内涵
   - 比较研究: 能与其他文学作品进行对比
   - 版本鉴别: 了解不同版本差异

## Rules

1. 回答原则：
   - 基于文本: 所有回答必须严格依据原著文本
   - 严谨准确: 不妄加猜测，不传播未经考证的观点
   - 深度解析: 透过表面现象揭示深层含义
   - 客观公正: 避免个人主观臆断

2. 行为准则：
   - 引经据典: 重要观点需引用原文佐证
   - 语言典雅: 保持与原著相称的文雅风格
   - 层次分明: 回答要有逻辑性和条理性
   - 深入浅出: 复杂问题要解释得通俗易懂

3. 限制条件：
   - 不涉争议: 避免介入红学争议性话题
   - 不妄评续作: 对后四十回保持审慎态度
   - 不越文本: 不脱离文本过度解读
   - 不代作者: 不以作者口吻发表观点

## Workflows

- 目标: 提供专业准确的红楼梦解读
- 步骤 1: 仔细理解用户问题，明确询问重点
- 步骤 2: 检索相关文本段落，确认信息准确性
- 步骤 3: 组织回答内容，适当引用原文
- 步骤 4: 以典雅文风呈现完整解答
- 预期结果: 用户获得权威、深入的红楼梦知识

## Initialization
作为红楼梦研究专家，你必须遵守上述Rules，按照Workflows执行任务。
""".strip()
        user_prompt = f"""
基于已下的文档内容回答:
{context}

问题：{query}""".strip()
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content":system_prompt},
                    {"role": "user", "content":user_prompt}
                ],
                max_tokens=1000,
                stream = False,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            error_type = (type(e)).__name__
            error_details = str(e) if str(e) else "未知错误"
            print(f"生成答案时出错：{error_type}-{error_details}")
            return f"生成答案时出错：{error_type}-{error_details}"

    def ask(self,question:str,top_k:int=10,similarity_threshold:float=0.01):
        #搜索相关文档
        relevant_chunks = self.search_chunks(question, top_k, similarity_threshold)
        if not relevant_chunks:
            return {
                "question":question,
                "answer":"抱歉，没有在文档中找到与您问题相关的内容",
                "sources":[],
            }
        print(f"找到{len(relevant_chunks)}个相关片段")
        #调用大模型（deep seek）生成答案
        print("正在生成答案")
        answer = self.generate_answer(question, relevant_chunks)
        #整理来源信息
        sources = []
        for chunk in relevant_chunks:
            sources.append(
                {
                    "source":chunk['source'],
                    "similarity":chunk["similarity"],
                    "content_preview":chunk['content'][:100] + '...' if len(chunk['content']) > 100 else chunk['content'],
                }
            )
        return {
            "question":question,
            "answer":answer,
            "sources":sources,
        }
            





def main():
    rag = RagSystem(load_api_key())
    rag.initialize()
    # 交互式问答
    print("——智能图书问答系统——")
    print("输入你的问题,输入“quit”或者‘exit’退出")
    while True:
        question = input("请输入你的问题:").strip()
        if question.lower() in["quit", "exit"]:
            print("感谢使用系统。")
            break
        if not question:
            continue
        #获取答案
        result = rag.ask(question)
        #显示结果
        print(f"\n答案：  {result['answer']}")

        if result['sources']:
            print("\n相关的文档片段: ")
            for i, source in enumerate(result['sources'], 1):
                print(f"{i}. 来源: {source['source']} (相似度: {source['similarity']:.3f})")
                print(f"内容预览: {source['content_preview']}")


if __name__=="__main__":
    main()