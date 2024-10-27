import argparse
from transformers import pipeline, TrOCRProcessor, VisionEncoderDecoderModel
import pyperclip
import io
import requests
from PIL import Image
from tkinter import Tk, filedialog
from tkinter import messagebox
import logging
import os
import numpy as np

# Limit the number of CPU cores to 3
os.environ["OMP_NUM_THREADS"] = "3"
os.environ["MKL_NUM_THREADS"] = "3"
os.environ["PYTHONHASHSEED"] = "0"  # For reproducibility

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Function to get image data from URL
def get_image_from_url(url):
    """
    Fetches image data from a given URL.

    Args:
        url (str): The URL of the image.

    Returns:
        io.BytesIO: A BytesIO object containing the image data, or None if an error occurs.
    """
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise an exception for bad status codes
        return io.BytesIO(response.content)
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching image from URL: {e}")
        return None

# Function to open a file dialog and get the image file path(s)
def get_image_from_filedialog():
    """
    Opens a file dialog to allow the user to select one or more image files.

    Returns:
        list: A list of file paths for the selected image files, or an empty list if no files are selected.
    """
    root = Tk()
    root.withdraw()  # Hide the main window
    file_paths = filedialog.askopenfilenames(
        initialdir="/",
        title="Select one or more image files",
        filetypes=(("Image files", "*.jpg *.jpeg *.png"), ("all files", "*.*"))
    )
    root.destroy()
    return file_paths

# Function to handle clipboard image
def get_image_from_clipboard():
    """
    Gets an image from the clipboard and returns it as a single-item list.

    Returns:
        list: A list containing the image data or an empty list if no image is found.
    """
    try:
        image_data = pyperclip.paste()
        if image_data.startswith("http"):  # Check if URL
            image_data = get_image_from_url(image_data)
            if not image_data:
                logging.error("Error fetching image from URL. Exiting...")
                return []
            return [Image.open(image_data)]
        else:
            image = Image.open(io.BytesIO(image_data))
            return [image]
    except (pyperclip.PyperclipException, IOError, TypeError):
        logging.info("No image found in clipboard. Returning empty list.")
        return []
def preprocess_image(image):
    # Convert to RGB if it's RGBA
    if image.mode == 'RGBA':
        image = image.convert('RGB')
    
    # Convert the image to a NumPy array
    image_np = np.array(image)

    # Check the shape and ensure it's in (height, width, channels)
    if image_np.ndim == 3 and image_np.shape[2] == 3:
        return image_np
    elif image_np.ndim == 3 and image_np.shape[2] == 4:
        # Optionally handle RGBA to RGB conversion here
        return image_np[:, :, :3]  # Discard the alpha channel
    else:
        raise ValueError("Unexpected image shape: {}".format(image_np.shape))
def process_images(model_name, images):
    """
    Processes the list of images and generates captions.

    Args:
        model_name (str): The name of the model to use for the pipeline.
        images (list): A list of PIL Image objects.
    """
    processor = TrOCRProcessor.from_pretrained(model_name)
    model = VisionEncoderDecoderModel.from_pretrained(model_name)

    for image in images:
        try:
            # Convert PIL image to NumPy array
            image_np = preprocess_image(image)
            # Log the image shape
            logging.info(f"Processing image with shape: {image_np.shape}")

            # Generate the caption
            logging.info("Generating caption...")

            # Process the image
            pixel_values = processor(image_np, return_tensors="pt").pixel_values

            # Generate text with max_new_tokens
            generated_ids = model.generate(pixel_values, max_new_tokens=99999999)

            # Decode and print the generated text
            caption = processor.decode(generated_ids[0], skip_special_tokens=True)

            # Print the caption
            logging.info(f"Caption: {caption}")
            print(caption)

            # Copy the caption to the clipboard
            logging.info("Copying caption to clipboard...")
            pyperclip.copy(caption)
            logging.info("Caption copied to clipboard.")
        except Exception as e:
            logging.error(f"Error processing image: {e}")
# Main function
def main():
    """
    Main function to process the image(s) and generate captions.
    """
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Generate captions for images.")
    parser.add_argument("-f", "--files", nargs="*", help="List of image file paths")
    parser.add_argument("-c", "--clipboard", default=True, action="store_true", help="Read image from clipboard")
    parser.add_argument("-m", "--model", default="microsoft/trocr-small-", help="Name of the model to use for the pipeline")
    parser.add_argument("-w", "--handwritten", action="store_true", default=False, help="Use the handwritten model instead of printed")
    args = parser.parse_args()
    model_name = args.model
    if model_name[-1] == '-':
        model_name += "handwritten" if args.handwritten else "printed"

    # Get image data based on source
    if args.clipboard:
        images = get_image_from_clipboard()
        if not images:
            logging.info("No image found in clipboard. Opening file dialog...")
            file_paths = get_image_from_filedialog()
            if not file_paths:
                messagebox.showerror("Error", "No image(s) selected.")
                logging.error("No image(s) selected. Exiting...")
                return
            images = [Image.open(path) for path in file_paths]
    else:
        if args.files:
            images = [Image.open(file_path) for file_path in args.files]
        else:
            logging.info("No files provided. Opening file dialog...")
            file_paths = get_image_from_filedialog()
            if not file_paths:
                messagebox.showerror("Error", "No image(s) selected.")
                logging.error("No image(s) selected. Exiting...")
                return
            images = [Image.open(path) for path in file_paths]

    process_images(model_name, images)

if __name__ == "__main__":
    main()