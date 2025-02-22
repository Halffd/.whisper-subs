from diffusers import FluxPipeline
import torch
import logging

# Enable logging
logging.basicConfig(level=logging.DEBUG)

try:
    # Load the pipeline
    pipe = FluxPipeline.from_pretrained("black-forest-labs/FLUX.1-schnell", torch_dtype=torch.float32)
    pipe.enable_model_cpu_offload()

    # Define the prompt
    prompt = "Megumin"

    # Generate the image
    out = pipe(
        prompt=prompt,
        guidance_scale=0.0,
        height=320,
        width=640,
        num_inference_steps=2,
        max_sequence_length=16,
    ).images[0]

    # Save the output image
    out.save("image.png")
    print("Image saved as image.png")

except Exception as e:
    logging.error(f"An error occurred: {e}")
"""
# Load model
pipe = FluxPipeline.from_pretrained("black-forest-labs/FLUX.1-schnell", torch_dtype=torch.bfloat16)
pipe.enable_sequential_cpu_offload()
#pipe = DiffusionPipeline.from_single_file("black-forest-labs/FLUX.1-schnell", use_safetensors=True, torch_dtype=torch.float8_e4m3fn, token=hf_token)
#pipe.save_pretrained("FLUX1-schnell", safe_serialization=True, use_safetensors=True)

# Generate output
input_text = "Yunyun"
output = pipe(input_text, num_return_sequences=1, max_length=50, temperature=0.7)

# Display the output
for i, sample in enumerate(output):
    print(f"Output {i + 1}: {sample['generated_text']}")
    """