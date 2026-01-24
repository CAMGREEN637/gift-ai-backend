def gift_prompt(info):
    return f"""
    You are gift recommendation engine.
    
    Return EXACT JSON - no commentary, no markdown, no extra text.
    
    Output format:
    [
        {{
        "name": "string",
        "price": number,
        "reason": "string"
        "category": "string"
        }}
    ]
    Rules
    -Exactly 5 items
    -Price must be under ${info.budget}
    -Categories must be concise
    
    Partner info:
    Name: {info.name}
    Age: {info.age}
    Interest: {",".join(info.interest)}
    Occasion: {info.occasion}
    """
