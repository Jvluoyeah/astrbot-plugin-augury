import json
import random
from datetime import date

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger, AstrBotConfig

FORTUNES = ["大吉", "中吉", "小吉", "吉", "末吉", "凶", "大凶"]


class AuguryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    def _cache_key(self, user_id: str, content: str) -> str:
        today = date.today().isoformat()
        persona = self.config.get("persona_id", "")
        return f"augury_{user_id}_{today}_{persona}_{content}"

    @filter.command("占卜")
    async def augury(self, event: AstrMessageEvent, *, content: str = None):
        if not content or not content.strip():
            yield event.plain_result("用法: /占卜 <你想占卜的事项>")
            return

        content = content.strip()
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
