import torch
import matplotlib.pyplot as plt
from safetensors.torch import load_file

def load_model(model_path):
    """Load the SafeTensors model."""
    checkpoint = torch.load(model_path, map_location='cpu')
    print(checkpoint.keys())
    return load_file(model_path)

def generate_input_data(input_size):
    """Generate random input data."""
    return torch.randn(input_size)

def evaluate_model(model, X_test):
    """Evaluate the model and return predictions."""
    model.eval()  # Set the model to evaluation mode
    with torch.no_grad():
        return model(X_test)

def calculate_metrics(y_true, y_pred):
    """Calculate performance metrics."""
    mse = torch.mean((y_pred.squeeze() - y_true) ** 2).item()
    mae = torch.mean(torch.abs(y_pred.squeeze() - y_true)).item()
    r_squared = 1 - (torch.sum((y_true - y_pred.squeeze()) ** 2).item() /
                     torch.sum((y_true - torch.mean(y_true)) ** 2).item())
    
    # Calculate additional metrics
    size = y_pred.numel()  # Total number of elements in the prediction tensor
    precision = torch.mean((y_pred.squeeze() - y_true) < 0.1).item()  # Example precision threshold
    error_rate = torch.mean((y_pred.squeeze() != y_true).float()).item()  # Rate of errors

    return mse, mae, r_squared, size, precision, error_rate

def plot_results(y_true, y_pred, metrics):
    """Plot the true vs predicted values."""
    mse, mae, r_squared, size, precision, error_rate = metrics
    plt.figure(figsize=(10, 5))
    plt.plot(y_true.numpy(), label='True Values', color='blue')
    plt.plot(y_pred.numpy(), label='Predicted Values', color='red', linestyle='--')
    plt.title(f'Model Performance\nMSE: {mse:.4f}, MAE: {mae:.4f}, R²: {r_squared:.4f}, '
              f'Size: {size}, Precision: {precision:.2f}, Error Rate: {error_rate:.2f}')
    plt.xlabel('Sample Index')
    plt.ylabel('Value')
    plt.legend()
    plt.grid()
    plt.show()

def select_file():
    """Open a file dialog to select a SafeTensors file."""
    from tkinter import filedialog
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()  # Hide the root window
    file_path = filedialog.askopenfilename(title="Select a SafeTensors file",
                                            filetypes=[("SafeTensors files", "*.safetensors")])
    return file_path

def main():
    """Main function to run the model evaluation."""
    model_path = select_file()  # Open file dialog to select model file

    if model_path:
        model = load_model(model_path)

        # Generate random input data
        input_size = (100, 10)  # Example input size
        X_test = generate_input_data(input_size)

        # Evaluate the model
        y_pred = evaluate_model(model, X_test)

        # Generate random true labels for comparison
        y_true = torch.randn(input_size[0])  # Same number of samples as X_test

        # Calculate performance metrics
        metrics = calculate_metrics(y_true, y_pred)

        # Plot performance metrics
        plot_results(y_true, y_pred, metrics)
    else:
        print("No file selected.")

if __name__ == "__main__":
    main()