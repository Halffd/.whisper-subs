# Use the official Debian base image
FROM debian:bullseye

# Set environment variables
ENV CONDA_DIR=/opt/conda
ENV PATH="$CONDA_DIR/bin:$PATH"

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget \
    bzip2 \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda
RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/conda.sh && \
    bash /tmp/conda.sh -b -p $CONDA_DIR && \
    rm /tmp/conda.sh

# Install CUDA (change the version as needed)
RUN wget https://developer.download.nvidia.com/compute/cuda/11.8.0/local_installers/cuda-repo-debian10-11-8-local_11.8.0-1_amd64.deb && \
    dpkg -i cuda-repo-debian10-11-8-local_11.8.0-1_amd64.deb && \
    apt-key add /var/cuda-repo-debian10-11-8-local/7fa2af80.pub && \
    apt-get update && \
    apt-get install -y cuda

# Install PyTorch with CUDA support
RUN conda install pytorch torchvision torchaudio cudatoolkit=11.8 -c pytorch

# Set the default command
CMD ["bash"]
