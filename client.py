import os

from openai import OpenAI


def ask_ai(prompt):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)
    response = client.responses.create(model="gpt-5-mini", input=prompt)
    return response.output_text


if __name__ == "__main__":
    print(ask_ai("Write a one-sentence bedtime story about a unicorn."))