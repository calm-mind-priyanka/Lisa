import random

# Base phrases for different styles
BASE_PHRASES = {
    "pop": [
        "Love is in the air", "Feel the beat tonight", "Your eyes, my sky",
        "Dance till the morning", "Heart on fire", "Take my hand and fly",
        "Lost in your rhythm", "We shine tonight", "Hold me close", "Chasing the stars"
    ],
    "romantic": [
        "My heart beats for you", "Under moonlight we sway", "Forever in your arms",
        "Whispered words of love", "Lost in your eyes", "Dreaming of you",
        "Your smile lights me", "Close to your soul", "Never let go", "You are my world"
    ],
    "edm": [
        "Drop the bass", "Feel the night ignite", "Raving till dawn",
        "Electric hearts collide", "Hands up high", "Pulse racing fast",
        "Dance all night", "Lights and sound", "Bass in my veins", "Energy unites us"
    ]
}

def generate_hooks(style="pop", count=10000):
    """
    Generates a list of random hooks.
    :param style: 'pop', 'romantic', 'edm', etc.
    :param count: Number of hooks to generate
    :return: List of hooks
    """
    hooks = []
    base_list = BASE_PHRASES.get(style, BASE_PHRASES["pop"])
    
    for _ in range(count):
        hook = random.choice(base_list)
        variation = f"{random.choice(['', '!', '?', '...'])} #{random.randint(1,9999)}"
        hooks.append(hook + variation)
    
    return till
