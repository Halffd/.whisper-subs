import torch
from transformers import GPT2LMHeadModel, GPT2Tokenizer

def generate_text_actually_working(prompt, max_length=50, temperature=2.0):
    print("Loading model...")
    tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
    model = GPT2LMHeadModel.from_pretrained('gpt2')
    
    # Fix the pad token issue
    tokenizer.pad_token = tokenizer.eos_token
    
    print("Encoding input...")
    inputs = tokenizer.encode(prompt, return_tensors='pt')
    
    print("Generating...")
    with torch.no_grad():
        outputs = model.generate(
            inputs,
            max_length=len(inputs[0]) + max_length,  # Add to input length
            temperature=temperature,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
            attention_mask=torch.ones_like(inputs),  # Fix attention mask
            no_repeat_ngram_size=2,  # Prevent loops
            early_stopping=True
        )
    
    result = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return result

# Test it
result = generate_text_actually_working('python', max_length=30, temperature=1.5)
print(f"\nGenerated: {result}")