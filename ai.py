from openai import OpenAI
import time
client = OpenAI(
    base_url="http://192.168.1.169:1234/v1",
    api_key="none"
)



def request(messages: list,temperature: float):
    response = client.chat.completions.create(
        model="google/gemma-4-e4b",
        messages=messages,
        temperature=temperature
    )
    with open("log.txt","a", encoding="utf-8") as file:
        file.write(str(response)+"\n")
    return response.choices[0].message.content