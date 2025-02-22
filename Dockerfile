FROM nvidia/cuda:12.3.1-runtime-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    xclip \
    xsel \
    libqt5gui5 \
    libxcb-xinerama0 \
    libdbus-1-3 \
    gosu \
    python3-pyqt5 \
    python3-pyqt5.qtmultimedia \
    qtbase5-dev \
    qtchooser \
    qt5-qmake \
    qtbase5-dev-tools \
    x11-apps \
    libxkbcommon-x11-0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    openssh-server \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Copy application files
COPY . .

# Set display environment variable
ENV DISPLAY=:0
ENV QT_X11_NO_MITSHM=1
ENV XDG_RUNTIME_DIR=/tmp/runtime-root
ENV QT_QPA_PLATFORM=xcb
ENV NO_AT_BRIDGE=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV QT_DEBUG_PLUGINS=1

# Create runtime directory with correct permissions
RUN mkdir -p /tmp/runtime-root && \
    chmod 700 /tmp/runtime-root && \
    mkdir -p /run/sshd

# Setup SSH for X11 forwarding
RUN sed -i 's/#X11Forwarding no/X11Forwarding yes/' /etc/ssh/sshd_config && \
    sed -i 's/#X11UseLocalhost yes/X11UseLocalhost no/' /etc/ssh/sshd_config

# Create directory for Documents
RUN mkdir -p /root/Documents

# Add entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
