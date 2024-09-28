import numpy as np
import matplotlib.pyplot as plt

# Parameters
frequency = 3.87521  # Frequency of the signal in Hz
sampling_rate = 37  # Sampling rate in Hz
duration = 4.3  # Duration in seconds

# Time vectors
t_continuous = np.linspace(0, duration, 1000)  # Continuous time
t_sampled = np.arange(0, duration, 1/sampling_rate)  # Sampled time

# Generate the continuous signal using Euler's formula
continuous_signal = np.exp(1j * 2 * np.pi * frequency * t_continuous)

# Sample the signal
sampled_signal = continuous_signal[::sampling_rate]

# Adjust sampled time vector to match the sampled signal
t_sampled = t_continuous[::sampling_rate]

# Plotting
plt.figure(figsize=(12, 6))

# Plot continuous signal
plt.subplot(2, 1, 1)
plt.plot(t_continuous, continuous_signal.real, label='Real Part (Cosine)')
plt.plot(t_continuous, continuous_signal.imag, label='Imaginary Part (Sine)', linestyle='--')
plt.title('Continuous Signal using Euler\'s Formula')
plt.xlabel('Time (s)')
plt.ylabel('Amplitude')
plt.grid()
plt.legend()

# Plot sampled signal
plt.subplot(2, 1, 2)
plt.stem(t_sampled, sampled_signal.real, linefmt='r-', markerfmt='ro', basefmt=' ')
plt.title('Sampled Signal')
plt.xlabel('Time (s)')
plt.ylabel('Amplitude')
plt.grid()

plt.tight_layout()
plt.show()