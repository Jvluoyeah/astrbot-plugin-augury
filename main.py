import json
import random
from datetime import date

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger, AstrBotConfig

FORTUNES = ["大吉", "中吉", "小吉", "吉", "末吉", "凶", "大凶"]
DEFAULT_SAFETY_BLOCK_MESSAGE = "抱歉，该占卜内容不符合正向价值观或存在安全风险，无法为您占卜。"
UNSAFE_KEYWORDS = (
    "自杀", "自残", "轻生", "跳楼", "割腕", "寻死",
    "杀人", "谋杀", "行凶", "伤害他人", "报复", "下毒", "投毒", "纵火",
    "爆炸", "炸弹", "恐怖袭击", "绑架", "抢劫", "盗窃", "偷窃",
    "诈骗", "洗钱", "走私", "贩毒", "吸毒", "制毒",
    "赌博", "涉黄", "色情", "嫖娼", "强奸", "猥亵", "性侵",
    "邪教", "传销",
)


class AuguryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    def _cache_key(self, user_id: str, content: str) -> str:
        today = date.today().isoformat()
        persona = self.config.get("persona_id", "")
        return f"augury_{user_id}_{today}_{persona}_{content}"

    async def _is_content_safe(self, content: str, umo: str) -> bool:
        """Check whether divination content conforms to normal/positive values."""
        if any(kw in content for kw in UNSAFE_KEYWORDS):
            return False

        try:
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            if provider_id:
                safety_prompt = (
                    "你是一个内容安全审核助手。请判断以下用户用于占卜的事项是否符合正向价值观与法律法规。\n"
                    "若内容涉及违法犯罪、暴力伤害、自杀自残、色情低俗、赌博诈骗、涉毒、恐怖极端、恶意攻击或违背公序良俗等不良内容，请回复：UNSAFE\n"
                    "若为正常的日常生活、学习、工作、情感、运势等占卜事项，请回复：SAFE\n"
                    "只输出 SAFE 或 UNSAFE，不要输出其他任何内容。\n\n"
                    f"占卜事项：{content}"
                )
                llm_resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=safety_prompt,
                )
                verdict = (llm_resp.completion_text or "").strip().upper()
                if "UNSAFE" in verdict:
                    return False
        except Exception as e:
            logger.warning(f"安全限制 LLM 检测失败，已回退至关键词检测: {e}")

        return True

    @filter.command("占卜")
    async def augury(self, event: AstrMessageEvent, *, content: str = None):
        content = "" if content is None else str(content).strip()
        if not content:
            yield event.plain_result("用法: /占卜 <你想占卜的事项>")
            return

        if self.config.get("enable_safety_check", True):
            if not await self._is_content_safe(content, event.unified_msg_origin):
                block_msg = (
                    str(self.config.get("safety_block_message") or "").strip()
                    or DEFAULT_SAFETY_BLOCK_MESSAGE
                )
                yield event.plain_result(block_msg)
                return
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        key = self._cache_key(user_id, content)

        cached = await self.get_kv_data(key, None)
        if cached is not None:
            if isinstance(cached, str):
                cached = json.loads(cached)
            result = cached["result"]
            explanation = cached.get("explanation", "")
        else:
            result = random.choice(FORTUNES)
            explanation = ""
            if self.config.get("enable_llm", False):
                try:
                    umo = event.unified_msg_origin
                    provider_id = await self.context.get_current_chat_provider_id(umo=umo)
                    if provider_id:
                        max_chars = self.config.get("llm_max_chars", 50)
                        system_prompt = ""
                        persona_id = self.config.get("persona_id", "")
                        if persona_id:
                            persona = await self.context.persona_manager.get_persona(persona_id)
                            if persona:
                                system_prompt = persona.system_prompt

                        if system_prompt:
                            prompt = (
                                f"{system_prompt}\n\n"
                                f"用户占卜的内容是：{content}，结果是：{result}。"
                                f"请用{max_chars}字以内给出解释，直接输出解释内容，不要前缀。"
                            )
                        else:
                            prompt = (
                                f"用户占卜的内容是：{content}，结果是：{result}。"
                                f"请用{max_chars}字以内给出解释，直接输出解释内容，不要前缀。"
                            )

                        llm_resp = await self.context.llm_generate(
                            chat_provider_id=provider_id,
                            prompt=prompt,
                        )
                        explanation = llm_resp.completion_text[:max_chars]
                        logger.info(f"LLM 解释: {explanation}")
                except Exception as e:
                    logger.warning(f"LLM 解释生成失败: {e}")

            await self.put_kv_data(key, json.dumps({
                "result": result,
                "explanation": explanation,
            }, ensure_ascii=False))

        today_str = date.today().strftime("%Y年%m月%d日")
        lines = [
            f"今天是{today_str}",
            f"{user_name}所求事项: 【{content}】",
            "",
            f"结果: 【{result}】",
        ]
        if explanation:
            lines.append(f"解释: {explanation}")

        yield event.plain_result("\n".join(lines))

    async def terminate(self):
        pass
