from types import SimpleNamespace

from ModuleFolders.Base.Base import Base
from ModuleFolders.Service.TaskExecutor import TranslatorUtil
from ModuleFolders.Infrastructure.TaskConfig.TaskConfig import TaskConfig
from ModuleFolders.Domain.PromptBuilder.PromptBuilder import PromptBuilder
from ModuleFolders.Domain.PromptBuilder.DynamicGlossary import apply_dynamic_glossary

class PromptBuilderLocal(Base):

    def __init__(self) -> None:
        super().__init__()

    # 获取默认系统提示词，优先从内存中读取，如果没有，则从文件中读取
    def get_system_default(config: TaskConfig) -> str:
        if getattr(PromptBuilderLocal, "local_system_zh", None) == None:
            with open("./Resource/Prompt/Local/local_system_zh.txt", "r", encoding = "utf-8") as reader:
                PromptBuilderLocal.local_system_zh = reader.read().strip()
        if getattr(PromptBuilderLocal, "local_system_en", None) == None:
            with open("./Resource/Prompt/Local/local_system_en.txt", "r", encoding = "utf-8") as reader:
                PromptBuilderLocal.local_system_en = reader.read().strip()


        # 如果输入的是字典，则转换为命名空间
        if isinstance(config, dict):
            namespace = SimpleNamespace()
            for key, value in config.items():
                setattr(namespace, key, value)
            config = namespace


        # 构造结果
        if config == None:
            result = PromptBuilderLocal.local_system_zh
        elif  config.target_language in ("chinese_simplified", "chinese_traditional"):
            result = PromptBuilderLocal.local_system_zh
        elif config.target_language not in ("chinese_simplified", "chinese_traditional"):
            result = PromptBuilderLocal.local_system_en

        return result

    # 获取系统提示词
    def build_system(config: TaskConfig, source_lang: str) -> str:

        # 获取默认系统提示词
        PromptBuilderLocal.get_system_default(config)

        en_sl, source_language, en_tl, target_language = TranslatorUtil.get_language_display_names(source_lang, config.target_language)

        # 构造结果
        if config == None:
            result = PromptBuilderLocal.local_system_zh
        elif config.target_language in ("chinese_simplified", "chinese_traditional"):
            result = PromptBuilderLocal.local_system_zh
        elif config.target_language not in ("chinese_simplified", "chinese_traditional"):
            result = PromptBuilderLocal.local_system_en
            source_language = en_sl
            target_language = en_tl

        return result.replace("{source_language}", source_language).replace("{target_language}", target_language).strip()

    # 构造术语表
    def build_glossary_prompt(config: TaskConfig, input_dict: dict) -> str:
        if getattr(config, "dynamic_glossary_switch", False):
            apply_dynamic_glossary(config, getattr(config, "dynamic_glossary_volume", None))

        # 将输入字典中的所有值合并为一个字符串，方便正则全局匹配
        full_text = "\n".join(input_dict.values())

        result = PromptBuilder.find_glossary_matches(config.prompt_dictionary_data, full_text)

        # 数据校验
        if len(result) == 0:
            return ""

        # 避免空的默认内容
        if len(result) == 1 and (result[0]["src"] == ""):
            return ""

        # 初始化变量，以免出错
        glossary_prompt_lines = []

        if config.target_language in ("chinese_simplified", "chinese_traditional"):
            # 添加开头
            glossary_prompt_lines.append(
                "\n###术语表"
                + "\n" + "原文|译文|备注"
            )

            # 添加数据
            for v in result:
                glossary_prompt_lines.append(f"{v.get("src")}|{v.get("dst")}|{v.get("info") if v.get("info") != "" else " "}")

        else:
            # 添加开头
            glossary_prompt_lines.append(
                "\n###Glossary"
                + "\n" + "Original Text|Translation|Remarks"
            )

            # 添加数据
            for v in result:
                glossary_prompt_lines.append(f"{v.get("src")}|{v.get("dst")}|{v.get("info") if v.get("info") != "" else " "}")


        # 拼接成最终的字符串
        glossary_prompt = "\n".join(glossary_prompt_lines)

        return glossary_prompt

    # 生成信息结构 - LocalLLM
    def generate_prompt_LocalLLM(config,  source_text_dict: dict, previous_text_list: list[str], source_lang, rag_context: str = "") -> tuple[list[dict], str, list[str]]:
        # 储存指令
        messages = []
        # 储存额外日志
        extra_log = []

        # 基础提示词
        system = PromptBuilderLocal.build_system(config, source_lang)

        # 如果有 RAG 上下文，注入到系统中
        if rag_context:
            if config.target_language in ("chinese_simplified", "chinese_traditional"):
                system += f"\n\n### 相关历史上下文（供参考）：\n{rag_context}\n"
            else:
                system += f"\n\n### Relevant Historical Context (for reference):\n{rag_context}\n"
            extra_log.append(f"RAG Context added:\n{rag_context}")

        # 术语表
        if config.prompt_dictionary_switch == True:
            result = PromptBuilderLocal.build_glossary_prompt(config, source_text_dict)
            if result != "":
                system = system + "\n" + result
                extra_log.append(result)

        # 构建待翻译文本
        source_text = PromptBuilder.build_source_text(config,source_text_dict)
        pre_prompt = PromptBuilder.build_userQueryPrefix(config) # 用户提问前置文本
        source_text_str = f"{pre_prompt}<textarea>\n{source_text}\n</textarea>"


        # 构建用户提问信息
        messages.append(
            {
                "role": "user",
                "content": source_text_str,
            }
        )


        return messages, system, extra_log
