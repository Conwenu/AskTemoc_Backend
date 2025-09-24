import asyncio

async def generate_answer(query: str) -> str:
    await asyncio.sleep(1) 
    return f"Answer: {query}"

class RAGService:
    def __init__(self):
        pass

    async def answer(self, query: str) -> str:
        answer = await generate_answer(query=query)
        return answer

    