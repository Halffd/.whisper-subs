import torch
from diffusers import FluxPipeline
import os

# Set the desired directory for Hugging Face models
os.environ["HF_HOME"] = "D:/HuggingFace"
os.environ["TRANSFORMERS_CACHE"] = "D:/HuggingFace"

# Load the pipeline with mixed precision
pipe = FluxPipeline.from_pretrained("black-forest-labs/FLUX.1-dev", torch_dtype=torch.float16)

# Enable model CPU offload to save VRAM
pipe.enable_model_cpu_offload()

# Define the prompt and optimized parameters
prompt = "Megumin"
image = pipe(
    prompt,
    height=256,  # Reduced height
    width=256,   # Reduced width
    guidance_scale=1.0,  # Lower guidance scale
    num_inference_steps=1,  # Reduced steps
    max_sequence_length=256,  # Lower max sequence length
    generator=torch.Generator("cuda").manual_seed(0)
).images[0]

# Save the generated image
image.save("flux-dev-optimized.png")