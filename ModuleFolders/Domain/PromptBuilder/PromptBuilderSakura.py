from types import SimpleNamespace

from ModuleFolders.Base.Base import Base
from ModuleFolders.Infrastructure.TaskConfig.TaskConfig import TaskConfig
from ModuleFolders.Domain.PromptBuilder.PromptBuilder import PromptBuilder
from ModuleFolders.Domain.PromptBuilder.DynamicGlossary import apply_dynamic_glossary, filter_legacy_references_for_prompt

class PromptBuilderSakura(Base):

    def __init__(self) -> None:
        super().__init__()

    # 获取默认系统提示词，优先从内存中读取，如果没有，则从文件中读取
    def get_system_default(config: TaskConfig) -> str:
        if getattr(PromptBuilderSakura, "sakura_system_zh", None) == None:
            with open("./Resource/Prompt/Sakura/sakura_system_zh.txt", "r", encoding = "utf-8") as reader:
                PromptBuilderSakura.sakura_system_zh = reader.read().strip()


        # 如果输入的是字典，则转换为命名空间
        if isinstance(config, dict):
            namespace = SimpleNamespace()
            for key, value in config.items():
                setattr(namespace, key, value)
            config = namespace


        # 构造结果
        result = PromptBuilderSakura.sakura_system_zh

        return result

    # 获取系统提示词
    def build_system(config: TaskConfig, _source_lang: str) -> str:
        PromptBuilderSakura.get_system_default(config)

        # 构造结果
        result = PromptBuilderSakura.sakura_system_zh


        return result



    # 构造术语表
    def build_glossary(config: TaskConfig, input_dict: dict) -> str:
        if getattr(config, "dynamic_glossary_switch", False):
            apply_dynamic_glossary(config, getattr(config, "dynamic_glossary_volume", None))
        filter_legacy_references_for_prompt(config)

        # 将输入字典中的所有值合并为一个字符串，方便正则全局匹配
        full_text = "\n".join(input_dict.values())

        result = PromptBuilder.find_glossary_matches(config.prompt_dictionary_data, full_text)

        if len(result) == 0:
            return ""

        # 构建指令词典文本
        dict_lines = []
        for item in result:
            src = item.get("src", "")
            dst = item.get("dst", "")
            info = item.get("info", "")

            if info == "":
                dict_lines.append(f"{src}->{dst}")
            else:
                dict_lines.append(f"{src}->{dst} #{info}")

        # 如果指令词典文本不为空
        if dict_lines:
            dict_lines_str = "\n".join(dict_lines)
        else:
            return ""

        return dict_lines_str

    # 生成信息结构 - Sakura
    def generate_prompt_sakura(config,  source_text_dict: dict, previous_text_list: list[str], source_lang, rag_context: str = "", translation_memory_references: list[dict] | None = None) -> tuple[list[dict], str, list[str]]:
        # 储存指令
        messages = []
        # 储存额外日志
        extra_log = []

        system = PromptBuilderSakura.build_system(config, source_lang)


        # 如果开启术语表
        glossary = ""
        if config.prompt_dictionary_switch == True:
            glossary = PromptBuilderSakura.build_glossary(config, source_text_dict)
            if glossary != "":
                extra_log.append(glossary)

        # 构建待翻译文本
        source_text = PromptBuilder.build_source_text(config,source_text_dict)

        # 构建主要提示词
        if glossary == "":
            user_prompt = "将下面的日文文本翻译成中文：\n" + source_text
        else:
            user_prompt = (
                "根据以下术语表（可以为空）：\n" + glossary
                + "\n" + "将下面的日文文本根据对应关系和备注翻译成中文：\n" + source_text
            )

        # 如果有 RAG 上下文，注入到主要提示词中
        if rag_context:
            user_prompt = f"### 相关历史上下文（供参考）：\n{rag_context}\n\n" + user_prompt
            extra_log.append(f"RAG Context added:\n{rag_context}")

        translation_memory = PromptBuilder.build_translation_memory_prompt(config, translation_memory_references)
        if translation_memory:
            user_prompt = translation_memory + "\n" + user_prompt
            extra_log.append(translation_memory)

        # 构建指令列表
        messages.append(
            {
                "role": "user",
                "content": user_prompt,
            }
        )

        return messages, system, extra_log
