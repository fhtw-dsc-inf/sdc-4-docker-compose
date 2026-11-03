import os
from typing import List, Dict

from openai import OpenAI, AsyncOpenAI
from pydantic import BaseModel


class FlaggedResponse(BaseModel):
    flagged: bool


class GPTService:
    def __init__(self, openai_api_key: str, profanity_prompt: str):
        self.client = OpenAI(api_key=openai_api_key, timeout=30.0)
        self.aclient = AsyncOpenAI(api_key=openai_api_key, timeout=30.0)
        self.profanity_prompt = profanity_prompt
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def aquery_gpt(self, message_history: list, query: str, model=None):
        return await self.aclient.chat.completions.create(
            model=model or self.model,
            messages=message_history + [{"role": "user", "content": query}],
            stream=True,
        )

    def query_gpt(self, message_history: List[Dict], query: str, model=None):
        return self.client.chat.completions.create(
            model=model or self.model,
            messages=message_history + [{"role": "user", "content": query}],
        )

    def get_ai_response(self, message_history, user_message: str) -> str:
        response = self.query_gpt(message_history, user_message)
        return response.choices[0].message.content or ""

    def contains_profanity(self, user_input: str) -> bool:
        response = self.client.chat.completions.parse(
            model=self.model,
            response_format=FlaggedResponse,
            messages=[
                {"role": "system", "content": self.profanity_prompt},
                {"role": "user", "content": user_input},
            ],
        )
        message = response.choices[0].message
        if message.refusal:
            return True
        if message.parsed is None:
            raise ValueError("OpenAI did not return a valid content-filter result.")
        return message.parsed.flagged
