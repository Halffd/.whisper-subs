import numpy as np
import torch
import torch.nn.functional as F
from transformers import GPT2LMHeadModel, GPT2Tokenizer


class LanguageModel(torch.nn.Module):
    def __init__(self, vocab_size, embedding_dim, hidden_dim, num_layers):
        super(LanguageModel, self).__init__()
        self.embedding = torch.nn.Embedding(vocab_size, embedding_dim)
        self.lstm = torch.nn.LSTM(
            embedding_dim, hidden_dim, num_layers, batch_first=True
        )
        self.fc = torch.nn.Linear(hidden_dim, vocab_size)

    def forward(self, input_ids, hidden=None):
        embedded = self.embedding(input_ids)
        output, hidden = self.lstm(embedded, hidden)
        logits = self.fc(output)
        return {'logits': logits, 'hidden': hidden}


def apply_temperature(logits, temperature):
    """
    Apply temperature scaling to the model's output logits.

    Args:
    logits (torch.Tensor): The original logits output by the model.
    temperature (float): The temperature value to apply.

    Returns:
    torch.Tensor: The scaled logits.
    """
    log_probs = F.log_softmax(logits / temperature, dim=-1)
    return log_probs


def generate_text(model, device, prompt, max_length, temperature=1.0):
    """
    Generate text using the language model with temperature scaling.

    Args:
    model (LanguageModel): The language model to use for generation.
    device (torch.device): The device to run the model on.
    prompt (str): The starting prompt for the text generation.
    max_length (int): The maximum length of the generated text.
    temperature (float): The temperature value to apply (default is 1.0).

    Returns:
    str: The generated text.
    """
    model.eval()
    input_ids = torch.tensor([model.tokenizer.encode(prompt)], device=device)
    generated = input_ids[0]
    print(generated)
    print()
    
    with torch.no_grad():
        hidden = None
        for _ in range(max_length):
            print(1, input_ids)
            print()
            output = model(input_ids, hidden)
            logits = output['logits'][:, -1, :]  # Get the last time step of the output
            print(2, logits.numpy())
            logits = apply_temperature(logits, temperature)
            next_token_id = torch.multinomial(torch.exp(logits), num_samples=1).item()
            generated = torch.cat((generated, torch.tensor([next_token_id], device=device)), dim=0)
            print()
            print('gen', generated)
            print()
            print(3, logits.numpy())
            print()
            input_ids = torch.tensor([[next_token_id]], device=device)
    print()
    print(generated)
    return model.tokenizer.decode(generated)


model = GPT2LMHeadModel.from_pretrained('gpt2')
tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
model.tokenizer = tokenizer
device = next(model.parameters()).device

generated_text = generate_text(model, device, 'python', max_length=22, temperature=2.0)
print(generated_text)