import json
import argparse
import logging
import tkinter as tk
from tkinter import filedialog
from diffusers import StableDiffusionPipeline
from diffusers.loaders import AttnProcsLayers
from safetensors.torch import load_file as load_safetensors
from PIL import Image
import torch

class LoRALoader:
    """
    LoRALoader class to manage loading of LoRA model, accepting parameters via 
    file input, argument parsing, and using a config file to control parameters.

    Attributes:
    -----------
    config : dict
        Stores all model parameters loaded from a config file.
    pipeline : StableDiffusionPipeline
        The Stable Diffusion pipeline with LoRA weights applied.
    negative_prompt : str
        Stores the negative prompt input for the model.
    enable_prompt_input : bool
        Controls whether the user can input prompts at the start.

    Methods:
    --------
    load_from_file(file_path: str) -> dict:
        Load parameters from a specified JSON config file.
    parse_arguments() -> dict:
        Parse command-line arguments for the model parameters.
    initialize_model(params: dict):
        Initialize the Stable Diffusion pipeline with LoRA weights.
    run_euler_method(learning_rate: float, epochs: int):
        Placeholder for the Euler method.
    select_model_file() -> str:
        Use file selector to choose a LoRA weights file.
    load_model_with_lora(lora_path: str):
        Load the base model and apply LoRA weights.
    generate_image(prompt: str):
        Generate an image using the loaded model.
    """

    def __init__(self, config_path: str = None, log_file: str = "lora_loader.log"):
        self.config = {}
        self.pipeline = None
        self.negative_prompt = ""
        self.enable_prompt_input = True  # Controls if the user can input prompts
        
        # Set up logging
        logging.basicConfig(filename=log_file, level=logging.INFO, 
                            format='%(asctime)s:%(levelname)s:%(message)s')

        if config_path:
            self.config = self.load_from_file(config_path)
        else:
            self.config = self.parse_arguments()

        self.enable_prompt_input = self.config.get("enable_prompt_input", True)

    def load_from_file(self, file_path: str) -> dict:
        """
        Load model parameters from a JSON configuration file.

        Parameters:
        -----------
        file_path : str
            Path to the JSON configuration file.

        Returns:
        --------
        dict:
            A dictionary of the loaded parameters.
        """
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)
                logging.info(f"Configuration loaded from {file_path}")
                return data
        except FileNotFoundError:
            logging.error(f"File {file_path} not found.")
            return {}
        except json.JSONDecodeError:
            logging.error("Error decoding JSON from the configuration file.")
            return {}

    def parse_arguments(self) -> dict:
        """
        Parse command-line arguments for LoRA model parameters.

        Returns:
        --------
        dict:
            A dictionary of parsed arguments.
        """
        parser = argparse.ArgumentParser(description="LoRA Model Loader")
        parser.add_argument("--config_path", type=str, help="Path to the configuration file")
        parser.add_argument("--lora_path", type=str, help="Path to the LoRA weights file")
        parser.add_argument("--negative_prompt", type=str, help="Negative prompt for the model")
        parser.add_argument("--prompt", type=str, help="Prompt for the model")
        parser.add_argument("--learning_rate", type=float, help="Learning rate for training", default=0.001)
        parser.add_argument("--epochs", type=int, help="Number of training epochs", default=10)
        parser.add_argument("--enable_prompt_input", type=bool, help="Enable user prompt input on start", default=True)
        args = parser.parse_args()
        return vars(args)

    def initialize_model(self, params: dict):
        """
        Initialize the Stable Diffusion pipeline with LoRA weights.

        Parameters:
        -----------
        params : dict
            A dictionary containing model parameters including the negative prompt.
        """
        self.negative_prompt = params.get('negative_prompt', '')
        prompt = params.get('prompt', 'default prompt')

        if self.enable_prompt_input:
            user_prompt = input("Please enter a prompt: ")
            prompt = user_prompt or prompt
        
        model_path = params.get('lora_path', None)
        if not model_path:
            model_path = self.select_model_file()
            logging.info(f"LoRA weights selected: {model_path}")
        
        if model_path:
            logging.info(f"Loading LoRA weights from {model_path}...")
            if model_path.endswith(".safetensors"):
                self.load_model_with_lora(model_path)
            else:
                logging.warning("The provided file is not in .safetensors format.")
        else:
            logging.warning("No LoRA weights file provided.")
        logging.info(f"Model initialized with prompt: {prompt} and negative prompt: {self.negative_prompt}")

    def run_euler_method(self, learning_rate: float, epochs: int):
        """
        Placeholder method for the Euler method.

        Parameters:
        -----------
        learning_rate : float
            The learning rate for the Euler method.
        epochs : int
            The number of iterations/epochs to run the Euler method.
        """
        logging.info(f"Running Euler method with learning rate: {learning_rate} for {epochs} epochs")
        current_value = 0
        for epoch in range(epochs):
            current_value += learning_rate
            logging.info(f"Epoch {epoch+1}/{epochs}: Current value = {current_value}")
        logging.info(f"Euler method completed. Final value: {current_value}")
        return current_value

    def select_model_file(self) -> str:
        """
        Open a file dialog to allow the user to select a LoRA weights file.

        Returns:
        --------
        str:
            Path to the selected LoRA weights file.
        """
        root = tk.Tk()
        root.withdraw()
        model_path = filedialog.askopenfilename(title="Select LoRA weights file", 
                                                filetypes=[("Safetensors Files", "*.safetensors"), 
                                                           ("All Files", "*.*")])
        return model_path

    def load_model_with_lora(self, lora_path: str):
        """
        Load the Stable Diffusion pipeline and apply LoRA weights from a safetensors file.

        Parameters:
        -----------
        lora_path : str
            The path to the LoRA weights in .safetensors format.
        """
        try:
            # Load the base Stable Diffusion model
            model_id = "runwayml/stable-diffusion-v1-5"
            logging.info(f"Loading base model: {model_id}")
            self.pipeline = StableDiffusionPipeline.from_pretrained(
                model_id, torch_dtype=torch.float16
            )
            self.pipeline.to("cuda")

            # Apply the LoRA weights
            logging.info(f"Applying LoRA weights from: {lora_path}")
            state_dict = load_safetensors(lora_path)
            lora_attn_procs = {}
            for key in state_dict.keys():
                module_name = key.split('.')[0]
                if module_name not in lora_attn_procs:
                    lora_attn_procs[module_name] = {}
                lora_attn_procs[module_name][key] = state_dict[key]
            attn_procs = AttnProcsLayers(self.pipeline.unet.attn_processors.keys())
            attn_procs.load_state_dict(lora_attn_procs, strict=False)
            self.pipeline.unet.set_attn_processor(attn_procs)
            logging.info("LoRA weights successfully applied.")
        except Exception as e:
            logging.error(f"Error loading model with LoRA: {e}")
            self.pipeline = None

    def generate_image(self, prompt: str):
        """
        Generate an image using the loaded LoRA-enhanced Stable Diffusion model.

        Parameters:
        -----------
        prompt : str
            The text prompt for image generation.
        """
        logging.info(f"Generating image with prompt: {prompt}")
        if self.pipeline is None:
            logging.error("Pipeline not initialized. Cannot generate image.")
            return

        negative_prompt = self.negative_prompt if self.negative_prompt else None

        # Generate the image
        with torch.autocast("cuda"):
            image = self.pipeline(prompt=prompt, negative_prompt=negative_prompt).images[0]

        # Save and show the image
        image.save("generated_image.png")
        logging.info("Image generated and saved as 'generated_image.png'.")
        image.show()

# Example usage:
# python lora_loader.py --lora_path path/to/your/lora_weights.safetensors --prompt "A beautiful landscape"
# Or initialize using a config file:
# loader = LoRALoader(config_path="config.json")
# loader.initialize_model(loader.config)
# loader.run_euler_method(loader.config.get('learning_rate', 0.001), loader.config.get('epochs', 10))
# loader.generate_image(loader.config.get('prompt', 'A city at night'))

# Example usage:
# python lora_loader.py --negative_prompt "avoid this"
# Or initialize using a config file:
loader = LoRALoader(config_path="lora.json")
loader.initialize_model(loader.config)
loader.run_euler_method(loader.config.get('learning_rate', 0.001), loader.config.get('epochs', 10))
loader.generate_image(loader.config.get('prompt', 'A city at night'))

